"""Tests for N6 Submit PR node.

See Issue #84 for specification.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from gh_link_auditor.pipeline.nodes.n6_submit_pr import (
    _apply_fixes,
    _extract_pr_number,
    _generate_commit_message,
    n6_submit_pr,
)
from gh_link_auditor.pipeline.state import (
    FixPatch,
    create_initial_state,
)


def _make_fix(
    source_file: str = "README.md",
    original_url: str = "https://old.example.com/page",
    replacement_url: str = "https://new.example.com/page",
) -> FixPatch:
    return FixPatch(
        source_file=source_file,
        original_url=original_url,
        replacement_url=replacement_url,
        unified_diff="--- a/README.md\n+++ b/README.md\n",
    )


class TestApplyFixes:
    """Tests for _apply_fixes()."""

    def test_replaces_url_in_file(self, tmp_path: Path) -> None:
        md = tmp_path / "README.md"
        md.write_text("Check [link](https://old.example.com/page) here.\n")
        fix = _make_fix(source_file="README.md")
        modified = _apply_fixes(tmp_path, [fix])
        assert modified == ["README.md"]
        assert "https://new.example.com/page" in md.read_text()
        assert "https://old.example.com/page" not in md.read_text()

    def test_skips_missing_file(self, tmp_path: Path) -> None:
        fix = _make_fix(source_file="nonexistent.md")
        modified = _apply_fixes(tmp_path, [fix])
        assert modified == []

    def test_skips_when_url_not_found(self, tmp_path: Path) -> None:
        md = tmp_path / "README.md"
        md.write_text("No matching URLs here.\n")
        fix = _make_fix(source_file="README.md")
        modified = _apply_fixes(tmp_path, [fix])
        assert modified == []

    def test_handles_multiple_fixes_same_file(self, tmp_path: Path) -> None:
        md = tmp_path / "README.md"
        md.write_text("Link1: https://a.com\nLink2: https://b.com\n")
        fixes = [
            _make_fix(
                source_file="README.md",
                original_url="https://a.com",
                replacement_url="https://a-new.com",
            ),
            _make_fix(
                source_file="README.md",
                original_url="https://b.com",
                replacement_url="https://b-new.com",
            ),
        ]
        modified = _apply_fixes(tmp_path, fixes)
        # File appears once even though two fixes apply
        assert modified == ["README.md"]
        content = md.read_text()
        assert "https://a-new.com" in content
        assert "https://b-new.com" in content

    def test_handles_multiple_files(self, tmp_path: Path) -> None:
        (tmp_path / "a.md").write_text("Link: https://old.com\n")
        (tmp_path / "b.md").write_text("Link: https://old2.com\n")
        fixes = [
            _make_fix(
                source_file="a.md",
                original_url="https://old.com",
                replacement_url="https://new.com",
            ),
            _make_fix(
                source_file="b.md",
                original_url="https://old2.com",
                replacement_url="https://new2.com",
            ),
        ]
        modified = _apply_fixes(tmp_path, fixes)
        assert sorted(modified) == ["a.md", "b.md"]

    def test_uses_str_replace_not_regex(self, tmp_path: Path) -> None:
        """Ensure we use str.replace, not regex — dots are literal."""
        md = tmp_path / "README.md"
        md.write_text("See https://example.com/page here.\n")
        # A regex would match "https://exampleXcom/page" — str.replace won't
        fix = _make_fix(
            source_file="README.md",
            original_url="https://example.com/page",
            replacement_url="https://new.example.com/page",
        )
        modified = _apply_fixes(tmp_path, [fix])
        assert modified == ["README.md"]

    def test_handles_subdirectory_file(self, tmp_path: Path) -> None:
        docs = tmp_path / "docs"
        docs.mkdir()
        md = docs / "guide.md"
        md.write_text("Link: https://old.example.com/page\n")
        fix = _make_fix(source_file="docs/guide.md")
        modified = _apply_fixes(tmp_path, [fix])
        assert modified == ["docs/guide.md"]


class TestExtractPrNumber:
    """Tests for _extract_pr_number()."""

    def test_standard_url(self) -> None:
        assert _extract_pr_number("https://github.com/owner/repo/pull/123") == 123

    def test_trailing_slash(self) -> None:
        assert _extract_pr_number("https://github.com/owner/repo/pull/456/") == 456

    def test_invalid_url(self) -> None:
        assert _extract_pr_number("not-a-url") == 0

    def test_empty_string(self) -> None:
        assert _extract_pr_number("") == 0

    def test_no_number(self) -> None:
        assert _extract_pr_number("https://github.com/owner/repo/pull/abc") == 0


class TestGenerateCommitMessage:
    """Tests for _generate_commit_message()."""

    def test_single_fix(self) -> None:
        msg = _generate_commit_message([_make_fix()])
        assert msg == "docs: fix broken link in README.md"

    def test_multiple_fixes_same_file(self) -> None:
        fixes = [_make_fix(), _make_fix(original_url="https://other.com")]
        msg = _generate_commit_message(fixes)
        assert "2 broken links" in msg
        assert "README.md" in msg

    def test_multiple_fixes_multiple_files(self) -> None:
        fixes = [
            _make_fix(source_file="a.md"),
            _make_fix(source_file="b.md"),
        ]
        msg = _generate_commit_message(fixes)
        assert "2 broken links" in msg
        assert "2 files" in msg


class TestN6SubmitPr:
    """Tests for n6_submit_pr() node function."""

    def test_skips_when_no_fixes(self) -> None:
        state = create_initial_state(target="https://github.com/org/repo")
        state["target_type"] = "url"
        state["fixes"] = []
        result = n6_submit_pr(state)
        assert "pr_url" not in result

    def test_skips_dry_run(self) -> None:
        state = create_initial_state(target="https://github.com/org/repo", dry_run=True)
        state["target_type"] = "url"
        state["fixes"] = [_make_fix()]
        result = n6_submit_pr(state)
        assert "pr_url" not in result

    def test_skips_local_target(self) -> None:
        state = create_initial_state(target="/some/path")
        state["target_type"] = "local"
        state["fixes"] = [_make_fix()]
        result = n6_submit_pr(state)
        assert "pr_url" not in result

    def test_errors_on_missing_owner(self) -> None:
        state = create_initial_state(target="https://github.com/org/repo")
        state["target_type"] = "url"
        state["repo_owner"] = ""
        state["repo_name_short"] = ""
        state["fixes"] = [_make_fix()]
        result = n6_submit_pr(state)
        assert any("missing owner/repo" in e for e in result.get("errors", []))

    def test_happy_path_mocked(self, tmp_path: Path) -> None:
        """Full N6 flow with all subprocess calls mocked."""
        state = create_initial_state(target="https://github.com/org/repo")
        state["target_type"] = "url"
        state["repo_owner"] = "org"
        state["repo_name_short"] = "repo"
        state["fixes"] = [_make_fix()]
        state["reviewed_verdicts"] = []

        # Create a fake clone directory
        clone_dir = tmp_path / "repo"
        clone_dir.mkdir()
        readme = clone_dir / "README.md"
        readme.write_text("Check [link](https://old.example.com/page) here.\n")

        mock_run_results = {
            "fork": _mock_completed("fork created"),
            "auth": _mock_completed("Logged in to github.com account testuser"),
            "clone": _mock_completed(""),
            "checkout": _mock_completed(""),
            "add": _mock_completed(""),
            "commit": _mock_completed(""),
            "push": _mock_completed(""),
            "default_branch": _mock_completed("main"),
            "pr_create": _mock_completed("https://github.com/org/repo/pull/42"),
        }

        def fake_run_gh(args, cwd=None):
            """Simulate gh CLI calls."""
            cmd = args[0] if args else ""
            if cmd == "repo" and "fork" in args:
                return mock_run_results["fork"]
            if cmd == "auth":
                return mock_run_results["auth"]
            if cmd == "repo" and "clone" in args:
                # Actually create the directory structure for clone
                return mock_run_results["clone"]
            if cmd == "api" and "user" in args:
                return _mock_completed("testuser")
            if cmd == "api" and ".default_branch" in str(args):
                return mock_run_results["default_branch"]
            if cmd == "pr":
                return mock_run_results["pr_create"]
            return _mock_completed("")

        def fake_subprocess_run(cmd, **kwargs):
            """Simulate git subprocess calls."""
            return _mock_completed("")

        with (
            patch(
                "gh_link_auditor.pipeline.nodes.n6_submit_pr._run_gh",
                side_effect=fake_run_gh,
            ),
            patch(
                "gh_link_auditor.pipeline.nodes.n6_submit_pr._clone_fork",
                return_value=clone_dir,
            ),
            patch(
                "subprocess.run",
                side_effect=fake_subprocess_run,
            ),
        ):
            result = n6_submit_pr(state)

        assert result.get("pr_url") == "https://github.com/org/repo/pull/42"
        assert result.get("pr_number") == 42

    def test_handles_fork_failure(self) -> None:
        state = create_initial_state(target="https://github.com/org/repo")
        state["target_type"] = "url"
        state["repo_owner"] = "org"
        state["repo_name_short"] = "repo"
        state["fixes"] = [_make_fix()]

        with patch(
            "gh_link_auditor.pipeline.nodes.n6_submit_pr._fork_repo",
            side_effect=RuntimeError("fork failed: permission denied"),
        ):
            result = n6_submit_pr(state)

        assert any("fork failed" in e for e in result.get("errors", []))
        assert "pr_url" not in result

    def test_handles_no_modified_files(self, tmp_path: Path) -> None:
        """If fixes don't actually change any files, skip PR creation."""
        state = create_initial_state(target="https://github.com/org/repo")
        state["target_type"] = "url"
        state["repo_owner"] = "org"
        state["repo_name_short"] = "repo"
        state["fixes"] = [_make_fix()]

        # Clone dir exists but file doesn't contain the URL
        clone_dir = tmp_path / "repo"
        clone_dir.mkdir()
        readme = clone_dir / "README.md"
        readme.write_text("No matching URLs here.\n")

        with (
            patch(
                "gh_link_auditor.pipeline.nodes.n6_submit_pr._fork_repo",
                return_value="testuser/repo",
            ),
            patch(
                "gh_link_auditor.pipeline.nodes.n6_submit_pr._clone_fork",
                return_value=clone_dir,
            ),
        ):
            result = n6_submit_pr(state)

        assert "pr_url" not in result


class TestForkRepo:
    """Tests for _fork_repo()."""

    def test_returns_fork_name(self) -> None:
        from gh_link_auditor.pipeline.nodes.n6_submit_pr import _fork_repo

        def fake_run_gh(args, cwd=None):
            if args[0] == "repo" and "fork" in args:
                return _mock_completed("Created fork testuser/myrepo")
            if args[0] == "auth":
                r = _mock_completed("")
                r.stderr = "Logged in to github.com account testuser (token)"
                return r
            return _mock_completed("")

        with patch(
            "gh_link_auditor.pipeline.nodes.n6_submit_pr._run_gh",
            side_effect=fake_run_gh,
        ):
            result = _fork_repo("upstream-org", "myrepo")

        assert result == "testuser/myrepo"

    def test_fallback_to_api_user(self) -> None:
        from gh_link_auditor.pipeline.nodes.n6_submit_pr import _fork_repo

        def fake_run_gh(args, cwd=None):
            if args[0] == "repo" and "fork" in args:
                return _mock_completed("forked")
            if args[0] == "auth":
                r = _mock_completed("")
                r.stderr = "no account info here"
                r.stdout = "no account info here"
                return r
            if args[0] == "api" and "user" in args:
                return _mock_completed("apiuser")
            return _mock_completed("")

        with patch(
            "gh_link_auditor.pipeline.nodes.n6_submit_pr._run_gh",
            side_effect=fake_run_gh,
        ):
            result = _fork_repo("org", "repo")

        assert result == "apiuser/repo"


class TestCloneFork:
    """Tests for _clone_fork()."""

    def test_returns_repo_dir(self, tmp_path: Path) -> None:
        from gh_link_auditor.pipeline.nodes.n6_submit_pr import _clone_fork

        def fake_run_gh(args, cwd=None):
            # Create the directory that clone would create
            repo_dir = tmp_path / "myrepo"
            repo_dir.mkdir(exist_ok=True)
            return _mock_completed("")

        with patch(
            "gh_link_auditor.pipeline.nodes.n6_submit_pr._run_gh",
            side_effect=fake_run_gh,
        ):
            result = _clone_fork("testuser/myrepo", tmp_path)

        assert result == tmp_path / "myrepo"


class TestGetDefaultBranch:
    """Tests for _get_default_branch()."""

    def test_returns_branch(self) -> None:
        from gh_link_auditor.pipeline.nodes.n6_submit_pr import _get_default_branch

        with patch(
            "gh_link_auditor.pipeline.nodes.n6_submit_pr._run_gh",
            return_value=_mock_completed("develop"),
        ):
            assert _get_default_branch("org", "repo") == "develop"

    def test_defaults_to_main(self) -> None:
        from gh_link_auditor.pipeline.nodes.n6_submit_pr import _get_default_branch

        with patch(
            "gh_link_auditor.pipeline.nodes.n6_submit_pr._run_gh",
            return_value=_mock_completed(""),
        ):
            assert _get_default_branch("org", "repo") == "main"


class TestRunGh:
    """Tests for _run_gh()."""

    def test_raises_on_failure(self) -> None:
        from gh_link_auditor.pipeline.nodes.n6_submit_pr import _run_gh

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _mock_completed("", returncode=1, stderr="error msg")
            with pytest.raises(RuntimeError, match="gh command failed"):
                _run_gh(["repo", "view"])

    def test_raises_when_gh_not_found(self) -> None:
        from gh_link_auditor.pipeline.nodes.n6_submit_pr import _run_gh

        with patch("subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(RuntimeError, match="gh CLI not found"):
                _run_gh(["repo", "view"])


# ---- Test helpers ----


class _MockCompletedProcess:
    """Simple mock for subprocess.CompletedProcess."""

    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _mock_completed(
    stdout: str = "",
    returncode: int = 0,
    stderr: str = "",
) -> _MockCompletedProcess:
    return _MockCompletedProcess(stdout=stdout, stderr=stderr, returncode=returncode)
