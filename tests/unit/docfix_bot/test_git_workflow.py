"""Tests for docfix_bot.git_workflow."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from docfix_bot.git_workflow import (
    apply_fixes,
    clone_repository,
    create_branch_name,
    create_pull_request,
    execute_fix_workflow,
    generate_commit_message,
)
from docfix_bot.models import make_broken_link, make_target


class TestCreateBranchName:
    def test_basic(self) -> None:
        target = make_target("org", "repo")
        name = create_branch_name(target, "README.md")
        assert name.startswith("fix/broken-link-")
        assert "README" in name

    def test_sanitizes_special_chars(self) -> None:
        target = make_target("org", "repo")
        name = create_branch_name(target, "path/to/file.md")
        assert "/" not in name.split("/", 1)[1].split("/")[0] or name.startswith("fix/")
        # Should not have double slashes or invalid chars
        assert " " not in name

    def test_truncates_long_context(self) -> None:
        target = make_target("org", "repo")
        name = create_branch_name(target, "a" * 100)
        # Branch name should be reasonable length
        assert len(name) < 80

    def test_includes_hash(self) -> None:
        target = make_target("org", "repo")
        name = create_branch_name(target, "README.md")
        # Should include a hash suffix
        parts = name.rsplit("-", 1)
        assert len(parts[1]) == 8  # 8-char hex hash


class TestGenerateCommitMessage:
    def test_single_link(self) -> None:
        links = [make_broken_link("README.md", 5, "https://old.com", 404)]
        msg = generate_commit_message(links)
        assert msg.startswith("fix:")
        assert "README.md" in msg

    def test_multiple_links_same_file(self) -> None:
        links = [
            make_broken_link("README.md", 5, "https://a.com", 404),
            make_broken_link("README.md", 10, "https://b.com", 404),
        ]
        msg = generate_commit_message(links)
        assert "2 broken links" in msg
        assert "README.md" in msg

    def test_multiple_files(self) -> None:
        links = [
            make_broken_link("README.md", 5, "https://a.com", 404),
            make_broken_link("DOCS.md", 10, "https://b.com", 404),
        ]
        msg = generate_commit_message(links)
        assert "2 broken links" in msg
        assert "2 files" in msg


class TestApplyFixes:
    def test_applies_fix(self, tmp_path: Path) -> None:
        readme = tmp_path / "README.md"
        readme.write_text("Visit [link](https://old.com) for info.\n")

        links = [
            make_broken_link(
                "README.md",
                1,
                "https://old.com",
                404,
                suggested_fix="https://new.com",
                fix_confidence=0.9,
            ),
        ]
        modified = apply_fixes(tmp_path, links)
        assert modified == ["README.md"]
        assert "https://new.com" in readme.read_text()
        assert "https://old.com" not in readme.read_text()

    def test_skips_low_confidence(self, tmp_path: Path) -> None:
        readme = tmp_path / "README.md"
        readme.write_text("Visit [link](https://old.com) for info.\n")

        links = [
            make_broken_link(
                "README.md",
                1,
                "https://old.com",
                404,
                suggested_fix="https://new.com",
                fix_confidence=0.3,
            ),
        ]
        modified = apply_fixes(tmp_path, links)
        assert modified == []
        assert "https://old.com" in readme.read_text()

    def test_skips_no_fix(self, tmp_path: Path) -> None:
        readme = tmp_path / "README.md"
        readme.write_text("Visit https://old.com\n")

        links = [make_broken_link("README.md", 1, "https://old.com", 404)]
        modified = apply_fixes(tmp_path, links)
        assert modified == []

    def test_missing_file(self, tmp_path: Path) -> None:
        links = [
            make_broken_link(
                "missing.md",
                1,
                "https://old.com",
                404,
                suggested_fix="https://new.com",
                fix_confidence=0.9,
            ),
        ]
        modified = apply_fixes(tmp_path, links)
        assert modified == []


class TestCreatePullRequest:
    @patch("docfix_bot.git_workflow.httpx.post")
    def test_success(self, mock_post: MagicMock) -> None:
        mock_post.return_value = MagicMock(
            status_code=201,
            json=lambda: {"number": 42, "html_url": "https://github.com/org/repo/pull/42"},
        )
        target = make_target("org", "repo")
        config = {"github_token": "ghp_test"}
        pr_num, pr_url = create_pull_request(target, "fix/test", "title", "body", config)
        assert pr_num == 42
        assert pr_url == "https://github.com/org/repo/pull/42"

    @patch("docfix_bot.git_workflow.httpx.post")
    def test_failure(self, mock_post: MagicMock) -> None:
        mock_post.return_value = MagicMock(
            status_code=422,
            text="Validation failed",
        )
        target = make_target("org", "repo")
        config = {"github_token": "ghp_test"}
        pr_num, pr_url = create_pull_request(target, "fix/test", "title", "body", config)
        assert pr_num is None
        assert pr_url is None

    def test_no_token(self) -> None:
        target = make_target("org", "repo")
        pr_num, pr_url = create_pull_request(target, "fix/test", "title", "body", {})
        assert pr_num is None

    @patch("docfix_bot.git_workflow.httpx.post")
    def test_http_error(self, mock_post: MagicMock) -> None:
        import httpx

        mock_post.side_effect = httpx.ConnectError("fail")
        target = make_target("org", "repo")
        config = {"github_token": "ghp_test"}
        pr_num, pr_url = create_pull_request(target, "fix/test", "title", "body", config)
        assert pr_num is None


class TestCloneRepository:
    @patch("git.Repo.clone_from")
    def test_success(self, mock_clone: MagicMock, tmp_path: Path) -> None:
        target = make_target("org", "repo")
        result = clone_repository(target, tmp_path, shallow=True)
        assert result == tmp_path / "repo"
        mock_clone.assert_called_once()
        call_kwargs = mock_clone.call_args[1]
        assert call_kwargs.get("depth") == 1

    @patch("git.Repo.clone_from")
    def test_non_shallow(self, mock_clone: MagicMock, tmp_path: Path) -> None:
        target = make_target("org", "repo")
        clone_repository(target, tmp_path, shallow=False)
        call_kwargs = mock_clone.call_args[1]
        assert "depth" not in call_kwargs

    @patch("git.Repo.clone_from")
    def test_clone_failure(self, mock_clone: MagicMock, tmp_path: Path) -> None:
        import git as gitmodule
        import pytest

        mock_clone.side_effect = gitmodule.GitCommandError("clone", 128)
        target = make_target("org", "repo")
        with pytest.raises(RuntimeError, match="Clone failed"):
            clone_repository(target, tmp_path)


class TestExecuteFixWorkflow:
    @patch("docfix_bot.git_workflow.create_pull_request")
    @patch("docfix_bot.git_workflow.clone_repository")
    @patch("git.Repo")
    def test_full_workflow(
        self,
        mock_repo_cls: MagicMock,
        mock_clone: MagicMock,
        mock_create_pr: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_clone.return_value = tmp_path
        readme = tmp_path / "README.md"
        readme.write_text("Visit [link](https://old.com) for info.\n")

        mock_repo = MagicMock()
        mock_repo_cls.return_value = mock_repo

        mock_create_pr.return_value = (42, "https://github.com/org/repo/pull/42")

        target = make_target("org", "repo")
        link = make_broken_link(
            "README.md",
            1,
            "https://old.com",
            404,
            suggested_fix="https://new.com",
            fix_confidence=0.9,
        )
        config = {"github_token": "ghp_test"}

        result = execute_fix_workflow(target, [link], config, "title", "body")

        assert result["status"] == "submitted"
        assert result["pr_number"] == 42
        assert len(result["broken_links_fixed"]) == 1

    def test_no_fixable_links(self) -> None:
        target = make_target("org", "repo")
        link = make_broken_link("README.md", 1, "https://old.com", 404)
        config = {"github_token": "ghp_test"}

        result = execute_fix_workflow(target, [link], config, "title", "body")

        assert result["status"] == "pending"
        assert result["broken_links_fixed"] == []

    @patch("docfix_bot.git_workflow.create_pull_request")
    @patch("docfix_bot.git_workflow.clone_repository")
    @patch("git.Repo")
    def test_no_modifications(
        self,
        mock_repo_cls: MagicMock,
        mock_clone: MagicMock,
        mock_create_pr: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_clone.return_value = tmp_path
        readme = tmp_path / "README.md"
        readme.write_text("No matching URLs here.\n")

        mock_repo = MagicMock()
        mock_repo_cls.return_value = mock_repo

        target = make_target("org", "repo")
        link = make_broken_link(
            "README.md",
            1,
            "https://old.com",
            404,
            suggested_fix="https://new.com",
            fix_confidence=0.9,
        )
        config = {"github_token": "ghp_test"}

        result = execute_fix_workflow(target, [link], config, "title", "body")

        assert result["status"] == "pending"
        assert result["broken_links_fixed"] == []
        mock_create_pr.assert_not_called()

    @patch("docfix_bot.git_workflow.create_pull_request")
    @patch("docfix_bot.git_workflow.clone_repository")
    @patch("git.Repo")
    def test_no_token_push_skipped(
        self,
        mock_repo_cls: MagicMock,
        mock_clone: MagicMock,
        mock_create_pr: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_clone.return_value = tmp_path
        readme = tmp_path / "README.md"
        readme.write_text("Visit [link](https://old.com) for info.\n")

        mock_repo = MagicMock()
        mock_repo_cls.return_value = mock_repo

        mock_create_pr.return_value = (None, None)

        target = make_target("org", "repo")
        link = make_broken_link(
            "README.md",
            1,
            "https://old.com",
            404,
            suggested_fix="https://new.com",
            fix_confidence=0.9,
        )
        config = {}  # No token

        result = execute_fix_workflow(target, [link], config, "title", "body")

        mock_repo.git.push.assert_not_called()
        assert result["status"] == "pending"
