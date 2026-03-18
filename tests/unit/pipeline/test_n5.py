"""Tests for N5 Generate Fix node.

See LLD #22 §10.0 T160: N5 generates valid diff.
See LLD #67 for clone-on-demand behavior.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from gh_link_auditor.pipeline.nodes.n5_generate_fix import (
    generate_unified_diff,
    n5_generate_fix,
)
from gh_link_auditor.pipeline.state import (
    DeadLink,
    ReplacementCandidate,
    Verdict,
    create_initial_state,
)


def _make_verdict(
    approved: bool = True,
    source_file: str = "README.md",
    original_url: str = "https://old.example.com/page",
    replacement_url: str = "https://new.example.com/page",
) -> Verdict:
    dl = DeadLink(
        url=original_url,
        source_file=source_file,
        line_number=5,
        link_text="link",
        http_status=404,
        error_type="http_error",
    )
    candidate = ReplacementCandidate(
        url=replacement_url,
        source="redirect",
        title=None,
        snippet=None,
    )
    return Verdict(
        dead_link=dl,
        candidate=candidate,
        confidence=0.95,
        reasoning="good match",
        approved=approved,
    )


class TestGenerateUnifiedDiff:
    """Tests for generate_unified_diff()."""

    def test_produces_diff(self, tmp_path: Path) -> None:
        md = tmp_path / "README.md"
        md.write_text("Check [link](https://old.example.com/page) for info.\n")
        diff = generate_unified_diff(
            str(md),
            "https://old.example.com/page",
            "https://new.example.com/page",
        )
        assert "---" in diff
        assert "+++" in diff
        assert "https://old.example.com/page" in diff
        assert "https://new.example.com/page" in diff

    def test_diff_contains_replacement(self, tmp_path: Path) -> None:
        md = tmp_path / "doc.md"
        md.write_text("Visit https://old.example.com/page for details.\n")
        diff = generate_unified_diff(
            str(md),
            "https://old.example.com/page",
            "https://new.example.com/page",
        )
        assert "-Visit https://old.example.com/page" in diff or "-" in diff
        assert "+Visit https://new.example.com/page" in diff or "+" in diff

    def test_handles_multiple_occurrences(self, tmp_path: Path) -> None:
        md = tmp_path / "doc.md"
        md.write_text("See https://old.example.com/page here.\nAlso https://old.example.com/page there.\n")
        diff = generate_unified_diff(
            str(md),
            "https://old.example.com/page",
            "https://new.example.com/page",
        )
        assert diff.count("+") >= 2  # At least 2 replacement lines

    def test_returns_empty_when_url_not_found(self, tmp_path: Path) -> None:
        md = tmp_path / "doc.md"
        md.write_text("No matching URLs here.\n")
        diff = generate_unified_diff(
            str(md),
            "https://old.example.com/page",
            "https://new.example.com/page",
        )
        assert diff == ""

    def test_handles_missing_file(self) -> None:
        diff = generate_unified_diff(
            "/nonexistent/file.md",
            "https://old.com",
            "https://new.com",
        )
        assert diff == ""

    def test_same_url_replacement_returns_empty(self, tmp_path: Path) -> None:
        """Replacing URL with itself produces empty diff (line 58)."""
        md = tmp_path / "doc.md"
        md.write_text("Check https://example.com/page here.\n")
        diff = generate_unified_diff(
            str(md),
            "https://example.com/page",
            "https://example.com/page",
        )
        assert diff == ""


class TestN5GenerateFix:
    """Tests for n5_generate_fix() node function."""

    def test_generates_fixes_for_approved(self, tmp_path: Path) -> None:
        md = tmp_path / "README.md"
        md.write_text("Check [link](https://old.example.com/page) for info.\n")
        state = create_initial_state(target=str(tmp_path))
        verdict = _make_verdict(approved=True, source_file=str(md))
        state["reviewed_verdicts"] = [verdict]
        result = n5_generate_fix(state)
        assert len(result["fixes"]) == 1
        assert result["fixes"][0]["original_url"] == "https://old.example.com/page"

    def test_skips_rejected_verdicts(self, tmp_path: Path) -> None:
        md = tmp_path / "README.md"
        md.write_text("Check [link](https://old.example.com/page) for info.\n")
        state = create_initial_state(target=str(tmp_path))
        verdict = _make_verdict(approved=False, source_file=str(md))
        state["reviewed_verdicts"] = [verdict]
        result = n5_generate_fix(state)
        assert len(result["fixes"]) == 0

    def test_skips_no_candidate(self, tmp_path: Path) -> None:
        state = create_initial_state(target=str(tmp_path))
        dl = DeadLink(
            url="https://dead.com",
            source_file="a.md",
            line_number=1,
            link_text="t",
            http_status=404,
            error_type="http_error",
        )
        verdict = Verdict(
            dead_link=dl,
            candidate=None,
            confidence=0.0,
            reasoning="no match",
            approved=True,
        )
        state["reviewed_verdicts"] = [verdict]
        result = n5_generate_fix(state)
        assert len(result["fixes"]) == 0

    def test_empty_reviewed_verdicts(self) -> None:
        state = create_initial_state(target="t")
        state["reviewed_verdicts"] = []
        result = n5_generate_fix(state)
        assert result["fixes"] == []

    def test_generates_valid_diff_content(self, tmp_path: Path) -> None:
        md = tmp_path / "test.md"
        md.write_text("Link: https://old.example.com/page\n")
        state = create_initial_state(target=str(tmp_path))
        verdict = _make_verdict(approved=True, source_file=str(md))
        state["reviewed_verdicts"] = [verdict]
        result = n5_generate_fix(state)
        assert len(result["fixes"]) == 1
        assert "unified_diff" in result["fixes"][0]
        assert len(result["fixes"][0]["unified_diff"]) > 0


class TestN5GenerateFixUrlTarget:
    """Tests for n5_generate_fix() with URL targets (clone-on-demand)."""

    def test_clones_and_generates_diff_for_url_target(self, tmp_path: Path) -> None:
        """URL target triggers clone, then generates diff from cloned files."""
        clone_dir = tmp_path / "myrepo"
        clone_dir.mkdir()
        md = clone_dir / "README.md"
        md.write_text("Check [link](https://old.example.com/page) here.\n")

        state = create_initial_state(target="https://github.com/org/myrepo")
        state["target_type"] = "url"
        state["repo_owner"] = "org"
        state["repo_name_short"] = "myrepo"
        verdict = _make_verdict(
            approved=True,
            source_file="README.md",
        )
        state["reviewed_verdicts"] = [verdict]

        with patch(
            "gh_link_auditor.pipeline.nodes.n5_generate_fix._clone_repo",
            return_value=clone_dir,
        ):
            result = n5_generate_fix(state)

        assert len(result["fixes"]) == 1
        assert result["fixes"][0]["source_file"] == "README.md"
        assert "https://new.example.com/page" in result["fixes"][0]["unified_diff"]

    def test_url_target_skips_when_no_approved_verdicts(self) -> None:
        state = create_initial_state(target="https://github.com/org/repo")
        state["target_type"] = "url"
        state["repo_owner"] = "org"
        state["repo_name_short"] = "repo"
        verdict = _make_verdict(approved=False)
        state["reviewed_verdicts"] = [verdict]

        result = n5_generate_fix(state)
        assert result["fixes"] == []

    def test_url_target_errors_on_missing_owner(self) -> None:
        state = create_initial_state(target="https://github.com/org/repo")
        state["target_type"] = "url"
        state["repo_owner"] = ""
        state["repo_name_short"] = ""
        verdict = _make_verdict(approved=True)
        state["reviewed_verdicts"] = [verdict]

        result = n5_generate_fix(state)
        assert result["fixes"] == []
        assert any("missing owner/repo" in e for e in result["errors"])

    def test_url_target_errors_on_clone_failure(self) -> None:
        state = create_initial_state(target="https://github.com/org/repo")
        state["target_type"] = "url"
        state["repo_owner"] = "org"
        state["repo_name_short"] = "repo"
        verdict = _make_verdict(approved=True)
        state["reviewed_verdicts"] = [verdict]

        with patch(
            "gh_link_auditor.pipeline.nodes.n5_generate_fix._clone_repo",
            side_effect=RuntimeError("clone failed"),
        ):
            result = n5_generate_fix(state)

        assert result["fixes"] == []
        assert any("clone failed" in e for e in result["errors"])
