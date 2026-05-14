"""Tests for bulk_scan.selection (#218 / hotfix #220)."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

from gh_link_auditor.bulk_scan import selection


def _fake_run(returncode: int = 0, stdout: str = "[]") -> MagicMock:
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    return m


class TestGhSearchOneSlice:
    """Cover the gh-search invocation. Locks the flag-form contract (#220)."""

    def test_uses_flag_form_not_bundled_query(self) -> None:
        """Regression: gh search rejects embedded qualifiers in the positional arg."""
        with patch.object(subprocess, "run", return_value=_fake_run(stdout="[]")) as r:
            selection._gh_search_one_slice(100, 150, "2025-05-14", limit=5)
        cmd = r.call_args[0][0]
        # No bundled-query positional after the subcommand
        assert cmd[:3] == ["gh", "search", "repos"]
        # Every qualifier MUST be flag-form
        assert "--language=Python" in cmd
        assert "--stars=100..150" in cmd
        assert "--archived=false" in cmd
        assert "--visibility=public" in cmd
        assert "--include-forks=false" in cmd
        assert "--updated=>2025-05-14" in cmd
        assert "--limit=5" in cmd

    def test_parses_results(self) -> None:
        payload = json.dumps(
            [
                {
                    "fullName": "owner/repo",
                    "stargazersCount": 200,
                    "pushedAt": "2026-01-01T00:00:00Z",
                    "isArchived": False,
                    "visibility": "public",
                }
            ]
        )
        with patch.object(subprocess, "run", return_value=_fake_run(stdout=payload)):
            out = selection._gh_search_one_slice(100, 300, "2025-01-01")
        assert len(out) == 1
        assert out[0]["fullName"] == "owner/repo"

    def test_logs_and_returns_empty_on_failure(self) -> None:
        """gh CLI exits non-zero → helper logs, returns [], never raises."""
        err = subprocess.CalledProcessError(1, ["gh"], output="", stderr="bad query")
        with patch.object(subprocess, "run", side_effect=err):
            out = selection._gh_search_one_slice(100, 200, "2025-01-01")
        assert out == []

    def test_handles_bad_json_silently(self) -> None:
        with patch.object(subprocess, "run", return_value=_fake_run(stdout="not json")):
            out = selection._gh_search_one_slice(100, 200, "2025-01-01")
        assert out == []

    def test_handles_timeout_silently(self) -> None:
        with patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired("gh", 120)):
            out = selection._gh_search_one_slice(100, 200, "2025-01-01")
        assert out == []


class TestSelectPythonRepos:
    """End-to-end selection generator behavior."""

    def _slice_fixture(self, n_per_slice: int = 2) -> list[dict]:
        return [
            {
                "fullName": f"owner/repo{i}",
                "stargazersCount": 200,
                "pushedAt": "2026-01-01T00:00:00Z",
                "isArchived": False,
                "visibility": "public",
            }
            for i in range(n_per_slice)
        ]

    def test_yields_up_to_target(self) -> None:
        # 2 slices × 2 UNIQUE repos each = 4 available; target 3 → stop at 3
        slice_a = [
            {
                "fullName": f"a/repo{i}",
                "stargazersCount": 200,
                "pushedAt": "2026-01-01T00:00:00Z",
                "isArchived": False,
                "visibility": "public",
            }
            for i in range(2)
        ]
        slice_b = [
            {
                "fullName": f"b/repo{i}",
                "stargazersCount": 200,
                "pushedAt": "2026-01-01T00:00:00Z",
                "isArchived": False,
                "visibility": "public",
            }
            for i in range(2)
        ]
        with patch.object(selection, "_gh_search_one_slice", side_effect=[slice_a, slice_b]):
            out = list(
                selection.select_python_repos(
                    3,
                    star_slices=[(100, 150), (150, 200)],
                    inter_request_sleep_s=0,
                )
            )
        assert len(out) == 3

    def test_dedupes_across_slices(self) -> None:
        # Same repo appears in both slices — count it once
        dup = self._slice_fixture(1)
        with patch.object(
            selection,
            "_gh_search_one_slice",
            side_effect=[dup, dup],
        ):
            out = list(
                selection.select_python_repos(
                    10,
                    star_slices=[(100, 150), (150, 200)],
                    inter_request_sleep_s=0,
                )
            )
        assert len(out) == 1

    def test_respects_blacklist(self) -> None:
        with patch.object(
            selection,
            "_gh_search_one_slice",
            return_value=[
                {
                    "fullName": "pallets/flask",
                    "stargazersCount": 60000,
                    "pushedAt": "2026-01-01T00:00:00Z",
                    "isArchived": False,
                    "visibility": "public",
                },
                {
                    "fullName": "ok/repo",
                    "stargazersCount": 200,
                    "pushedAt": "2026-01-01T00:00:00Z",
                    "isArchived": False,
                    "visibility": "public",
                },
            ],
        ):
            out = list(
                selection.select_python_repos(
                    10,
                    star_slices=[(100, 150)],
                    blacklisted_repos={"pallets/flask"},
                    inter_request_sleep_s=0,
                )
            )
        names = [r["full_name"] for r in out]
        # pallets/flask in blacklist; flask's stars also exceed MAX_STARS
        # so it's filtered twice — but the blacklist catches it first.
        assert "pallets/flask" not in names
        assert "ok/repo" in names

    def test_filters_archived(self) -> None:
        with patch.object(
            selection,
            "_gh_search_one_slice",
            return_value=[
                {
                    "fullName": "a/dead",
                    "stargazersCount": 200,
                    "pushedAt": "2026-01-01T00:00:00Z",
                    "isArchived": True,
                    "visibility": "public",
                },
                {
                    "fullName": "a/alive",
                    "stargazersCount": 200,
                    "pushedAt": "2026-01-01T00:00:00Z",
                    "isArchived": False,
                    "visibility": "public",
                },
            ],
        ):
            out = list(
                selection.select_python_repos(
                    10,
                    star_slices=[(100, 150)],
                    inter_request_sleep_s=0,
                )
            )
        names = [r["full_name"] for r in out]
        assert "a/dead" not in names
        assert "a/alive" in names

    def test_filters_out_of_star_range(self) -> None:
        with patch.object(
            selection,
            "_gh_search_one_slice",
            return_value=[
                {
                    "fullName": "too/small",
                    "stargazersCount": 50,  # < MIN_STARS=100
                    "pushedAt": "2026-01-01T00:00:00Z",
                    "isArchived": False,
                    "visibility": "public",
                },
                {
                    "fullName": "too/big",
                    "stargazersCount": 50000,  # > MAX_STARS=10000
                    "pushedAt": "2026-01-01T00:00:00Z",
                    "isArchived": False,
                    "visibility": "public",
                },
                {
                    "fullName": "just/right",
                    "stargazersCount": 500,
                    "pushedAt": "2026-01-01T00:00:00Z",
                    "isArchived": False,
                    "visibility": "public",
                },
            ],
        ):
            out = list(
                selection.select_python_repos(
                    10,
                    star_slices=[(100, 150)],
                    inter_request_sleep_s=0,
                )
            )
        assert [r["full_name"] for r in out] == ["just/right"]

    def test_empty_slice_response(self) -> None:
        with patch.object(selection, "_gh_search_one_slice", return_value=[]):
            out = list(
                selection.select_python_repos(
                    10,
                    star_slices=[(100, 150)],
                    inter_request_sleep_s=0,
                )
            )
        assert out == []
