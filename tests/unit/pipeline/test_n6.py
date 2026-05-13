"""Tests for N6 Submit PR node.

See Issue #84 for specification.
"""

from __future__ import annotations

from contextlib import contextmanager
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
        """Full N6 flow with all subprocess and REST calls mocked."""
        state = create_initial_state(target="https://github.com/org/repo")
        state["target_type"] = "url"
        state["repo_owner"] = "org"
        state["repo_name_short"] = "repo"
        state["fixes"] = [_make_fix()]
        state["reviewed_verdicts"] = []

        clone_dir = tmp_path / "repo"
        clone_dir.mkdir()
        readme = clone_dir / "README.md"
        readme.write_text("Check [link](https://old.example.com/page) here.\n")

        with (
            patch(
                "gh_link_auditor.pipeline.nodes.n6_submit_pr._fork_repo",
                return_value="testuser/repo",
            ),
            patch(
                "gh_link_auditor.pipeline.nodes.n6_submit_pr._clone_fork",
                return_value=clone_dir,
            ),
            patch(
                "gh_link_auditor.pipeline.nodes.n6_submit_pr._get_default_branch",
                return_value="main",
            ),
            patch(
                "gh_link_auditor.pipeline.nodes.n6_submit_pr._create_pr",
                return_value=("https://github.com/org/repo/pull/42", 42),
            ),
            patch("subprocess.run", return_value=_mock_completed("")),
        ):
            result = n6_submit_pr(state)

        assert result.get("pr_url") == "https://github.com/org/repo/pull/42"
        assert result.get("pr_number") == 42

    def test_writes_tier1_pending_trust_on_success(self, tmp_path: Path) -> None:
        """Issue #177: successful PR submission transitions repo trust to tier1_pending."""
        from gh_link_auditor.unified_db import UnifiedDatabase

        db_path = tmp_path / "ghla.db"
        state = create_initial_state(target="https://github.com/org/repo", db_path=str(db_path))
        state["target_type"] = "url"
        state["repo_owner"] = "org"
        state["repo_name_short"] = "repo"
        state["fixes"] = [_make_fix()]
        state["reviewed_verdicts"] = []

        clone_dir = tmp_path / "repo"
        clone_dir.mkdir()
        readme = clone_dir / "README.md"
        readme.write_text("Check [link](https://old.example.com/page) here.\n")

        with (
            patch(
                "gh_link_auditor.pipeline.nodes.n6_submit_pr._fork_repo",
                return_value="testuser/repo",
            ),
            patch(
                "gh_link_auditor.pipeline.nodes.n6_submit_pr._clone_fork",
                return_value=clone_dir,
            ),
            patch(
                "gh_link_auditor.pipeline.nodes.n6_submit_pr._get_default_branch",
                return_value="main",
            ),
            patch(
                "gh_link_auditor.pipeline.nodes.n6_submit_pr._create_pr",
                return_value=("https://github.com/org/repo/pull/42", 42),
            ),
            patch("subprocess.run", return_value=_mock_completed("")),
        ):
            result = n6_submit_pr(state)

        assert result.get("pr_url") == "https://github.com/org/repo/pull/42"

        with UnifiedDatabase(str(db_path)) as udb:
            trust = udb.get_repo_trust("org/repo")
        assert trust is not None
        assert trust["trust_level"] == "tier1_pending"
        assert trust["total_prs"] == 1

    def test_trust_update_failure_does_not_abort_pr(self, tmp_path: Path) -> None:
        """If the trust DB write throws, the PR still wins."""
        state = create_initial_state(target="https://github.com/org/repo", db_path="/nonexistent/dir/ghla.db")
        state["target_type"] = "url"
        state["repo_owner"] = "org"
        state["repo_name_short"] = "repo"
        state["fixes"] = [_make_fix()]
        state["reviewed_verdicts"] = []

        clone_dir = tmp_path / "repo"
        clone_dir.mkdir()
        (clone_dir / "README.md").write_text("Check [link](https://old.example.com/page) here.\n")

        with (
            patch(
                "gh_link_auditor.pipeline.nodes.n6_submit_pr._fork_repo",
                return_value="testuser/repo",
            ),
            patch(
                "gh_link_auditor.pipeline.nodes.n6_submit_pr._clone_fork",
                return_value=clone_dir,
            ),
            patch(
                "gh_link_auditor.pipeline.nodes.n6_submit_pr._get_default_branch",
                return_value="main",
            ),
            patch(
                "gh_link_auditor.pipeline.nodes.n6_submit_pr._create_pr",
                return_value=("https://github.com/org/repo/pull/42", 42),
            ),
            patch("subprocess.run", return_value=_mock_completed("")),
            patch(
                "gh_link_auditor.pr_tracker.update_trust_on_submit",
                side_effect=RuntimeError("simulated trust failure"),
            ),
        ):
            result = n6_submit_pr(state)

        assert result.get("pr_url") == "https://github.com/org/repo/pull/42"

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
    """Tests for _fork_repo() — classic-PAT REST implementation (issue #185)."""

    @staticmethod
    @contextmanager
    def _fake_classic_pat(token: str = "ghp_fake_classic"):
        yield token

    def test_returns_fork_full_name(self) -> None:
        from gh_link_auditor.pipeline.nodes.n6_submit_pr import _fork_repo
        from tests.fakes.http import FakeHTTPResponse

        fake_response = FakeHTTPResponse(
            status_code=202,
            body={"full_name": "martymcenroe/upstream-repo"},
        )
        with (
            patch(
                "gh_link_auditor.classic_pat.classic_pat_session",
                side_effect=self._fake_classic_pat,
            ),
            patch("httpx.post", return_value=fake_response) as mock_post,
        ):
            result = _fork_repo("upstream-org", "upstream-repo")

        assert result == "martymcenroe/upstream-repo"
        assert mock_post.call_args.args[0] == "https://api.github.com/repos/upstream-org/upstream-repo/forks"
        headers = mock_post.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer ghp_fake_classic"
        assert headers["Accept"] == "application/vnd.github+json"

    def test_raises_on_api_error(self) -> None:
        from gh_link_auditor.pipeline.nodes.n6_submit_pr import _fork_repo
        from tests.fakes.http import FakeHTTPResponse

        fake_response = FakeHTTPResponse(status_code=403, body={"message": "forbidden"})
        with (
            patch(
                "gh_link_auditor.classic_pat.classic_pat_session",
                side_effect=self._fake_classic_pat,
            ),
            patch("httpx.post", return_value=fake_response),
        ):
            with pytest.raises(Exception):
                _fork_repo("org", "repo")

    def test_propagates_classic_pat_decryption_failure(self) -> None:
        from gh_link_auditor.pipeline.nodes.n6_submit_pr import _fork_repo

        @contextmanager
        def boom(*_a, **_kw):
            raise RuntimeError("classic PAT unavailable")
            yield  # unreachable

        with patch(
            "gh_link_auditor.classic_pat.classic_pat_session",
            side_effect=boom,
        ):
            with pytest.raises(RuntimeError, match="classic PAT"):
                _fork_repo("org", "repo")


class TestCreatePr:
    """Tests for _create_pr() — classic-PAT REST implementation (issue #185)."""

    @staticmethod
    @contextmanager
    def _fake_classic_pat(token: str = "ghp_fake_classic"):
        yield token

    def test_returns_url_and_number(self) -> None:
        from gh_link_auditor.pipeline.nodes.n6_submit_pr import _create_pr
        from tests.fakes.http import FakeHTTPResponse

        fake_response = FakeHTTPResponse(
            status_code=201,
            body={
                "html_url": "https://github.com/org/repo/pull/42",
                "number": 42,
            },
        )
        with (
            patch(
                "gh_link_auditor.classic_pat.classic_pat_session",
                side_effect=self._fake_classic_pat,
            ),
            patch("httpx.post", return_value=fake_response) as mock_post,
        ):
            url, number = _create_pr("org", "repo", "user:branch", "main", "title", "body")

        assert url == "https://github.com/org/repo/pull/42"
        assert number == 42
        assert mock_post.call_args.args[0] == "https://api.github.com/repos/org/repo/pulls"
        payload = mock_post.call_args.kwargs["json"]
        assert payload == {
            "title": "title",
            "head": "user:branch",
            "base": "main",
            "body": "body",
        }

    def test_raises_on_api_error(self) -> None:
        from gh_link_auditor.pipeline.nodes.n6_submit_pr import _create_pr
        from tests.fakes.http import FakeHTTPResponse

        fake_response = FakeHTTPResponse(status_code=422, body={"message": "invalid"})
        with (
            patch(
                "gh_link_auditor.classic_pat.classic_pat_session",
                side_effect=self._fake_classic_pat,
            ),
            patch("httpx.post", return_value=fake_response),
        ):
            with pytest.raises(Exception):
                _create_pr("org", "repo", "user:branch", "main", "t", "b")


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
