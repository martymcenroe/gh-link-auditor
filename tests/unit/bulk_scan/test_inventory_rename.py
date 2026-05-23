"""Tests for #250 — follow GitHub repo-rename 301 redirects in Stage 1 inventory.

Three layers exercised here:

* ``RepoRenamed`` exception carries the new full_name.
* ``_resolve_renamed_repo`` extracts repo_id from a Location URL and looks
  up the current ``full_name`` via the GH API.
* ``_list_doc_files`` raises ``RepoRenamed`` on 301; ``inventory_repo``
  catches and retries once.

No MagicMock — local typed fakes only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest

from gh_link_auditor.bulk_scan import inventory

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass
class _FakeResp:
    status_code: int = 200
    body: dict[str, Any] | None = None
    headers: dict[str, str] = field(default_factory=dict)
    text: str = ""

    def json(self) -> dict[str, Any]:
        return self.body or {}

    def raise_for_status(self) -> None:
        if 300 <= self.status_code < 400 or self.status_code >= 400:
            request = httpx.Request("GET", "https://fake.test")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=request,
                response=response,
            )


class _ScriptedAPIClient:
    """Returns responses from a queue, one per call.

    If the queue exhausts, raises AssertionError — catches over-calling bugs.
    """

    def __init__(self, responses: list[_FakeResp]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> _FakeResp:
        self.calls.append((url, kwargs))
        assert self._responses, f"unexpected call to {url}"
        return self._responses.pop(0)


@dataclass
class _StubRawResp:
    status_code: int = 200
    text: str = ""


class _StubRawClient:
    """Returns 200 + empty body for any URL — for inventory_repo happy path."""

    def get(self, url: str, **kwargs: Any) -> _StubRawResp:
        return _StubRawResp()


# ---------------------------------------------------------------------------
# A. RepoRenamed exception
# ---------------------------------------------------------------------------


class TestRepoRenamedException:
    def test_carries_new_full_name(self) -> None:
        e = inventory.RepoRenamed("new/name")
        assert e.new_full_name == "new/name"

    def test_string_repr_mentions_new_name(self) -> None:
        e = inventory.RepoRenamed("foo/bar")
        assert "foo/bar" in str(e)


# ---------------------------------------------------------------------------
# B. _resolve_renamed_repo
# ---------------------------------------------------------------------------


class TestResolveRenamedRepo:
    def test_extracts_id_and_returns_new_full_name(self) -> None:
        api = _ScriptedAPIClient([_FakeResp(status_code=200, body={"full_name": "NewOwner/repo"})])
        result = inventory._resolve_renamed_repo(
            api,
            "https://api.github.com/repositories/969637328/git/trees/HEAD?recursive=1",
        )
        assert result == "NewOwner/repo"
        # Should have called /repositories/{id} exactly once.
        assert len(api.calls) == 1
        called_url, _ = api.calls[0]
        assert "/repositories/969637328" in called_url

    def test_returns_none_when_no_id_in_location(self) -> None:
        api = _ScriptedAPIClient([])  # should never be called
        result = inventory._resolve_renamed_repo(api, "https://api.github.com/foo/bar")
        assert result is None
        assert api.calls == []

    def test_returns_none_when_lookup_404s(self) -> None:
        api = _ScriptedAPIClient([_FakeResp(status_code=404)])
        result = inventory._resolve_renamed_repo(api, "https://api.github.com/repositories/123/git/trees/HEAD")
        assert result is None

    def test_returns_none_when_response_has_no_full_name(self) -> None:
        api = _ScriptedAPIClient(
            [_FakeResp(status_code=200, body={"id": 123})]  # no full_name
        )
        result = inventory._resolve_renamed_repo(api, "https://api.github.com/repositories/123/git/trees/HEAD")
        assert result is None

    def test_returns_none_when_lookup_raises(self) -> None:
        class _Boom:
            def get(self, url: str, **kwargs: Any) -> _FakeResp:
                raise httpx.ConnectError("network down")

        result = inventory._resolve_renamed_repo(
            _Boom(),
            "https://api.github.com/repositories/123/git/trees/HEAD",
        )
        assert result is None


# ---------------------------------------------------------------------------
# C. _list_doc_files 301 detection
# ---------------------------------------------------------------------------


class TestListDocFilesHandles301:
    def test_raises_repo_renamed_on_301_with_valid_location(self) -> None:
        # First call: 301 redirect with Location header.
        # Second call (the /repositories/{id} lookup): returns new full_name.
        api = _ScriptedAPIClient(
            [
                _FakeResp(
                    status_code=301,
                    headers={"Location": "https://api.github.com/repositories/969637328/git/trees/HEAD?recursive=1"},
                ),
                _FakeResp(status_code=200, body={"full_name": "NewOwner/LUFFY"}),
            ]
        )
        with pytest.raises(inventory.RepoRenamed) as exc:
            inventory._list_doc_files(api, "ElliottYan/LUFFY")
        assert exc.value.new_full_name == "NewOwner/LUFFY"

    def test_falls_through_when_301_location_unresolvable(self) -> None:
        # 301 with Location that has no /repositories/{id} pattern.
        api = _ScriptedAPIClient(
            [
                _FakeResp(
                    status_code=301,
                    headers={"Location": "https://example.com/elsewhere"},
                ),
            ]
        )
        with pytest.raises(httpx.HTTPStatusError):
            inventory._list_doc_files(api, "owner/repo")

    def test_404_still_raises_normal_httpstatuserror(self) -> None:
        api = _ScriptedAPIClient([_FakeResp(status_code=404)])
        with pytest.raises(httpx.HTTPStatusError):
            inventory._list_doc_files(api, "deleted/repo")

    def test_200_no_rename_no_exception(self) -> None:
        api = _ScriptedAPIClient([_FakeResp(status_code=200, body={"tree": [{"type": "blob", "path": "README.md"}]})])
        docs = inventory._list_doc_files(api, "owner/repo")
        assert docs == ["README.md"]


# ---------------------------------------------------------------------------
# D. inventory_repo retry behavior
# ---------------------------------------------------------------------------


class TestInventoryRepoHandlesRename:
    def test_rename_then_success_returns_renamed_from(self) -> None:
        # Call 1: 301 redirect.
        # Call 2: /repositories/{id} → new full_name.
        # Call 3: trees API for the new name → 200 with a blob.
        api = _ScriptedAPIClient(
            [
                _FakeResp(
                    status_code=301,
                    headers={"Location": "https://api.github.com/repositories/123/git/trees/HEAD?recursive=1"},
                ),
                _FakeResp(status_code=200, body={"full_name": "new/name"}),
                _FakeResp(status_code=200, body={"tree": [{"type": "blob", "path": "README.md"}]}),
            ]
        )
        raw = _StubRawClient()
        result = inventory.inventory_repo("old/name", api, raw)
        assert result["renamed_from"] == "old/name"
        assert result["current_full_name"] == "new/name"
        assert "README.md" in result["doc_files"]

    def test_no_rename_returns_renamed_from_none(self) -> None:
        api = _ScriptedAPIClient([_FakeResp(status_code=200, body={"tree": [{"type": "blob", "path": "README.md"}]})])
        raw = _StubRawClient()
        result = inventory.inventory_repo("owner/repo", api, raw)
        assert result["renamed_from"] is None
        assert result["current_full_name"] == "owner/repo"

    def test_double_rename_propagates(self) -> None:
        # Call 1: 301 redirect from old/name.
        # Call 2: /repositories/{id} → new/name.
        # Call 3: retry against new/name ALSO 301s.
        # Call 4: /repositories/{id2} → would be another newer/name, but the
        # retry doesn't catch RepoRenamed a second time, so the exception
        # propagates out of inventory_repo.
        api = _ScriptedAPIClient(
            [
                _FakeResp(
                    status_code=301,
                    headers={"Location": "https://api.github.com/repositories/100/git/trees/HEAD?recursive=1"},
                ),
                _FakeResp(status_code=200, body={"full_name": "second/name"}),
                _FakeResp(
                    status_code=301,
                    headers={"Location": "https://api.github.com/repositories/200/git/trees/HEAD?recursive=1"},
                ),
                _FakeResp(status_code=200, body={"full_name": "third/name"}),
            ]
        )
        raw = _StubRawClient()
        with pytest.raises(inventory.RepoRenamed):
            inventory.inventory_repo("first/name", api, raw)
