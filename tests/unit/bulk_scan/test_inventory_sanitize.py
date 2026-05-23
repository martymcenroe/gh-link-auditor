"""Tests for #251 — sanitize doc paths from GitHub trees API.

Covers two defenses:
* ``_list_doc_files`` drops paths containing C0 control chars (``\\n``, ``\\r``, ``\\t``).
* ``_fetch_raw`` URL-encodes the path component so spaces, ``#``, ``?`` etc.
  don't crash url parsing or pollute the URL structure.

No MagicMock — uses small typed fakes per the project's testing conventions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from gh_link_auditor.bulk_scan import inventory

# ---------------------------------------------------------------------------
# Tiny fakes — local to this test file to keep the fake surface minimal.
# ---------------------------------------------------------------------------


@dataclass
class _FakeTreeResp:
    """Minimal stand-in for the httpx Response from the trees API."""

    tree: list[dict[str, Any]]
    status_code: int = 200
    headers: dict[str, str] = field(default_factory=dict)

    def json(self) -> dict[str, Any]:
        return {"tree": self.tree}

    def raise_for_status(self) -> None:
        return None


class _FakeAPIClient:
    """Records GET calls and returns a pre-set trees-API response."""

    def __init__(self, tree: list[dict[str, Any]]) -> None:
        self._resp = _FakeTreeResp(tree=tree)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> _FakeTreeResp:
        self.calls.append((url, kwargs))
        return self._resp


@dataclass
class _RecordingResponse:
    """200 with empty body — enough to satisfy ``_fetch_raw`` happy path."""

    status_code: int = 200
    text: str = ""


@dataclass
class _RecordingRawClient:
    """Records the URLs ``_fetch_raw`` asks for; returns 200 + empty body."""

    seen_urls: list[str] = field(default_factory=list)

    def get(self, url: str, **kwargs: Any) -> _RecordingResponse:
        self.seen_urls.append(url)
        return _RecordingResponse()


# ---------------------------------------------------------------------------
# A. Path-filter tests at the trees-API layer
# ---------------------------------------------------------------------------


class TestListDocFilesSanitizesPaths:
    """`_list_doc_files` drops paths containing control characters."""

    def test_drops_path_with_newline(self) -> None:
        client = _FakeAPIClient(
            tree=[
                {"type": "blob", "path": "README.md"},
                {"type": "blob", "path": "docs/has\nweird.md"},
                {"type": "blob", "path": "docs/normal.md"},
            ]
        )
        docs = inventory._list_doc_files(client, "owner/repo")
        assert "README.md" in docs
        assert "docs/normal.md" in docs
        assert all("\n" not in p for p in docs), f"\\n leaked into: {docs}"

    def test_drops_path_with_carriage_return(self) -> None:
        client = _FakeAPIClient(
            tree=[
                {"type": "blob", "path": "README.md"},
                {"type": "blob", "path": "weird\rreadme.md"},
            ]
        )
        docs = inventory._list_doc_files(client, "owner/repo")
        assert docs == ["README.md"]

    def test_drops_path_with_tab(self) -> None:
        client = _FakeAPIClient(
            tree=[
                {"type": "blob", "path": "README.md"},
                {"type": "blob", "path": "docs/tabby\there.rst"},
            ]
        )
        docs = inventory._list_doc_files(client, "owner/repo")
        assert docs == ["README.md"]

    def test_drops_path_with_null_byte(self) -> None:
        client = _FakeAPIClient(
            tree=[
                {"type": "blob", "path": "README.md"},
                {"type": "blob", "path": "docs/null\x00byte.md"},
            ]
        )
        docs = inventory._list_doc_files(client, "owner/repo")
        assert docs == ["README.md"]

    def test_keeps_normal_doc_paths(self) -> None:
        tree = [
            {"type": "blob", "path": "README.md"},
            {"type": "blob", "path": "docs/foo.rst"},
            {"type": "blob", "path": "CHANGELOG.txt"},
            {"type": "blob", "path": "guide.adoc"},
            {"type": "blob", "path": "src/main.py"},  # non-doc — filtered by extension
        ]
        client = _FakeAPIClient(tree=tree)
        docs = inventory._list_doc_files(client, "owner/repo")
        assert "README.md" in docs
        assert "docs/foo.rst" in docs
        assert "CHANGELOG.txt" in docs
        assert "guide.adoc" in docs
        assert "src/main.py" not in docs

    def test_empty_tree_returns_empty_list(self) -> None:
        client = _FakeAPIClient(tree=[])
        assert inventory._list_doc_files(client, "owner/repo") == []


# ---------------------------------------------------------------------------
# B. URL-encoding tests at the raw-CDN fetch layer
# ---------------------------------------------------------------------------


class TestFetchRawURLEncodesPath:
    """`_fetch_raw` URL-encodes the path so surprise chars don't crash httpx."""

    def test_encodes_space_in_path(self) -> None:
        raw = _RecordingRawClient()
        inventory._fetch_raw(raw, "owner/repo", "docs/My File.md")
        assert len(raw.seen_urls) == 1
        url = raw.seen_urls[0]
        assert "My%20File" in url
        assert "My File" not in url

    def test_encodes_hash_in_path(self) -> None:
        raw = _RecordingRawClient()
        inventory._fetch_raw(raw, "owner/repo", "docs/file#tag.md")
        assert "%23" in raw.seen_urls[0]

    def test_encodes_question_mark_in_path(self) -> None:
        raw = _RecordingRawClient()
        inventory._fetch_raw(raw, "owner/repo", "docs/file?weird.md")
        assert "%3F" in raw.seen_urls[0]

    def test_keeps_directory_separators_literal(self) -> None:
        raw = _RecordingRawClient()
        inventory._fetch_raw(raw, "owner/repo", "a/b/c/d.md")
        url = raw.seen_urls[0]
        # Path separators must NOT be encoded — otherwise we'd 404 on raw CDN.
        assert "/a/b/c/d.md" in url
        assert "%2F" not in url

    def test_normal_ascii_path_unchanged(self) -> None:
        raw = _RecordingRawClient()
        inventory._fetch_raw(raw, "owner/repo", "README.md")
        assert raw.seen_urls[0].endswith("/owner/repo/HEAD/README.md")


# ---------------------------------------------------------------------------
# C. End-to-end: inventory_repo survives one pathological filename per #251
# ---------------------------------------------------------------------------


class TestInventoryRepoSurvivesPathologicalFilename:
    """The whole-repo-aborts-on-one-bad-path failure mode (deepscholar) is gone."""

    def test_inventory_returns_normal_files_even_when_pathological_present(
        self,
    ) -> None:
        # Tree response with one \n-containing path mixed in with normal ones.
        tree = [
            {"type": "blob", "path": "README.md"},
            {"type": "blob", "path": "docs/has\nweird.md"},
            {"type": "blob", "path": "docs/normal.md"},
        ]
        api = _FakeAPIClient(tree=tree)
        raw = _RecordingRawClient()
        result = inventory.inventory_repo("owner/repo", api, raw)
        # The pathological path was dropped at _list_doc_files; the raw fetches
        # therefore only attempt the two safe paths.
        assert "README.md" in result["doc_files"]
        assert "docs/normal.md" in result["doc_files"]
        assert all("\n" not in p for p in result["doc_files"])
        # And the raw client was only asked for safe URLs.
        assert all("%0A" not in u and "\n" not in u for u in raw.seen_urls)
