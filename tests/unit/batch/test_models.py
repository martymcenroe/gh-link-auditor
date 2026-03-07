"""Tests for batch data models and validation.

Covers LLD-019 scenarios:
- T250: Repo name validation rejects injection (REQ-3)
"""

from __future__ import annotations

import pytest

from gh_link_auditor.batch.exceptions import BatchInputError
from gh_link_auditor.batch.models import (
    BatchConfig,
    BatchState,
    RepoTask,
    TaskStatus,
    TokenState,
    validate_repo_name,
)


class TestExceptions:
    """Tests for batch exception hierarchy."""

    def test_all_tokens_exhausted_message(self) -> None:
        from gh_link_auditor.batch.exceptions import AllTokensExhaustedError

        exc = AllTokensExhaustedError(wait_time=120.0)
        assert exc.wait_time == 120.0
        assert "120" in str(exc)

    def test_insufficient_scopes_message(self) -> None:
        from gh_link_auditor.batch.exceptions import InsufficientScopesError

        exc = InsufficientScopesError("1234", ["repo", "public_repo"])
        assert exc.token_suffix == "1234"
        assert "repo" in str(exc)
        assert "1234" in str(exc)

    def test_rate_limit_exhausted(self) -> None:
        from gh_link_auditor.batch.exceptions import RateLimitExhaustedError

        exc = RateLimitExhaustedError(wait_time=60.0)
        assert exc.wait_time == 60.0
        assert "60" in str(exc)

    def test_batch_input_error(self) -> None:
        exc = BatchInputError("bad input")
        assert "bad input" in str(exc)


class TestTaskStatus:
    """Tests for TaskStatus enum."""

    def test_all_statuses_exist(self) -> None:
        assert TaskStatus.PENDING.value == "pending"
        assert TaskStatus.RUNNING.value == "running"
        assert TaskStatus.COMPLETED.value == "completed"
        assert TaskStatus.FAILED.value == "failed"
        assert TaskStatus.SKIPPED.value == "skipped"


class TestBatchConfig:
    """Tests for BatchConfig defaults."""

    def test_defaults(self, tmp_path) -> None:
        config = BatchConfig(target_list_path=tmp_path / "targets.json")
        assert config.concurrency == 1
        assert config.max_repos is None
        assert config.dry_run is False
        assert config.checkpoint_interval == 10
        assert config.max_disk_gb == 10.0

    def test_custom_values(self, tmp_path) -> None:
        config = BatchConfig(
            target_list_path=tmp_path / "targets.json",
            concurrency=5,
            max_repos=100,
            dry_run=True,
        )
        assert config.concurrency == 5
        assert config.max_repos == 100
        assert config.dry_run is True


class TestRepoTask:
    """Tests for RepoTask creation and defaults."""

    def test_defaults(self) -> None:
        task = RepoTask(repo_full_name="owner/repo", clone_url="https://github.com/owner/repo.git")
        assert task.status == TaskStatus.PENDING
        assert task.error_message is None
        assert task.links_found == 0
        assert task.pr_submitted is False

    def test_custom_values(self) -> None:
        task = RepoTask(
            repo_full_name="owner/repo",
            clone_url="https://github.com/owner/repo.git",
            status=TaskStatus.COMPLETED,
            links_found=10,
            pr_submitted=True,
            pr_url="https://github.com/owner/repo/pull/1",
        )
        assert task.status == TaskStatus.COMPLETED
        assert task.pr_url == "https://github.com/owner/repo/pull/1"


class TestTokenState:
    """Tests for TokenState repr masking."""

    def test_repr_masks_token(self) -> None:
        ts = TokenState(token="ghp_abcdefghijk1234567890")
        r = repr(ts)
        assert "ghp_abcdefghijk" not in r
        assert "...7890" in r

    def test_repr_short_token(self) -> None:
        ts = TokenState(token="abc")
        r = repr(ts)
        assert "****" in r


class TestBatchState:
    """Tests for BatchState creation."""

    def test_defaults(self) -> None:
        state = BatchState()
        assert state.batch_id  # UUID generated
        assert state.tasks == []
        assert state.current_index == 0

    def test_has_unique_ids(self) -> None:
        s1 = BatchState()
        s2 = BatchState()
        assert s1.batch_id != s2.batch_id


class TestValidateRepoName:
    """Tests for repo name validation — T250 (REQ-3)."""

    def test_valid_names(self) -> None:
        for name in ["owner/repo", "my-org/my.repo", "user_1/repo-2"]:
            validate_repo_name(name)  # Should not raise

    def test_rejects_path_traversal(self) -> None:
        with pytest.raises(BatchInputError, match="Invalid repository name"):
            validate_repo_name("../../../etc/passwd")

    def test_rejects_empty(self) -> None:
        with pytest.raises(BatchInputError):
            validate_repo_name("")

    def test_rejects_spaces(self) -> None:
        with pytest.raises(BatchInputError):
            validate_repo_name("owner/repo name")

    def test_rejects_no_slash(self) -> None:
        with pytest.raises(BatchInputError):
            validate_repo_name("justaname")

    def test_rejects_special_chars(self) -> None:
        with pytest.raises(BatchInputError):
            validate_repo_name("owner/repo;rm -rf /")
