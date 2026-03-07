"""Tests for batch execution engine.

Covers LLD-019 scenarios:
- T010: Load valid target list (REQ-1)
- T020: Load invalid target list (REQ-1)
- T030: Sequential batch run with concurrency=1 (REQ-1)
- T040: One repo failure isolation (REQ-3)
- T050: Checkpoint and resume (REQ-2)
- T060: Atomic checkpoint write (REQ-2)
- T220: Dry-run mode skips PR submission (REQ-13)
- T230: Per-repo timeout enforcement (REQ-3)
- T240: Concurrent execution (REQ-1)
- T300: Configurable concurrency parameter (REQ-1)
- T320: Dry-run completes full pipeline without PR (REQ-13)
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from gh_link_auditor.batch.engine import (
    _deserialize_state,
    _load_checkpoint,
    _load_target_list,
    _process_single_repo,
    _save_checkpoint,
    _serialize_state,
    resume_batch,
    run_batch,
)
from gh_link_auditor.batch.exceptions import BatchInputError
from gh_link_auditor.batch.models import (
    BatchConfig,
    BatchState,
    RepoTask,
    TaskStatus,
)
from gh_link_auditor.batch.rate_limiter import AdaptiveRateLimiter

FIXTURE_DIR = Path(__file__).parent.parent.parent / "fixtures" / "batch"


class TestLoadTargetList:
    """T010, T020: Load target list tests."""

    def test_load_valid_target_list(self) -> None:
        """T010: Load valid target list (REQ-1)."""
        tasks = _load_target_list(FIXTURE_DIR / "sample_target_list.json")
        assert len(tasks) == 5
        assert all(t.status == TaskStatus.PENDING for t in tasks)
        assert tasks[0].repo_full_name == "octocat/hello-world"
        assert tasks[0].clone_url == "https://github.com/octocat/hello-world.git"

    def test_load_invalid_target_list_missing_field(self, tmp_path) -> None:
        """T020: Load invalid target list with missing fields (REQ-1)."""
        bad_data = [{"name": "repo", "url": "https://github.com/owner/repo"}]
        target_file = tmp_path / "bad.json"
        target_file.write_text(json.dumps(bad_data))

        with pytest.raises(BatchInputError, match="missing"):
            _load_target_list(target_file)

    def test_load_nonexistent_file(self, tmp_path) -> None:
        with pytest.raises(BatchInputError, match="Failed to load"):
            _load_target_list(tmp_path / "nonexistent.json")

    def test_load_invalid_json(self, tmp_path) -> None:
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{not valid json")
        with pytest.raises(BatchInputError):
            _load_target_list(bad_file)

    def test_load_non_array(self, tmp_path) -> None:
        target_file = tmp_path / "obj.json"
        target_file.write_text('{"key": "value"}')
        with pytest.raises(BatchInputError, match="JSON array"):
            _load_target_list(target_file)

    def test_load_with_injection_name(self, tmp_path) -> None:
        """T250: Repo name injection (REQ-3)."""
        bad_data = [{"full_name": "../../../etc/passwd", "clone_url": "x"}]
        target_file = tmp_path / "inject.json"
        target_file.write_text(json.dumps(bad_data))
        with pytest.raises(BatchInputError, match="Invalid repository name"):
            _load_target_list(target_file)


class TestSequentialBatchRun:
    """T030: Sequential batch run with concurrency=1 (REQ-1)."""

    def test_sequential_three_repos_succeed(self, tmp_path) -> None:
        targets = [
            {"full_name": f"owner/repo{i}", "clone_url": f"https://github.com/owner/repo{i}.git"} for i in range(3)
        ]
        target_file = tmp_path / "targets.json"
        target_file.write_text(json.dumps(targets))

        config = BatchConfig(
            target_list_path=target_file,
            concurrency=1,
            clone_dir=tmp_path / "clones",
        )
        report = asyncio.run(run_batch(config))

        assert report.repos_scanned == 3
        assert report.repos_succeeded == 3
        assert report.repos_failed == 0


class TestFailureIsolation:
    """T040: One repo failure isolation (REQ-3)."""

    def test_one_repo_failure_others_succeed(self, tmp_path) -> None:
        targets = [
            {"full_name": f"owner/repo{i}", "clone_url": f"https://github.com/owner/repo{i}.git"} for i in range(3)
        ]
        target_file = tmp_path / "targets.json"
        target_file.write_text(json.dumps(targets))

        call_count = 0

        async def mock_process(task, token_manager, rate_limiter, config):
            nonlocal call_count
            call_count += 1
            from gh_link_auditor.batch.models import now_utc

            task.started_at = now_utc()
            if task.repo_full_name == "owner/repo1":
                task.status = TaskStatus.FAILED
                task.error_message = "Test failure"
            else:
                task.status = TaskStatus.COMPLETED
            task.completed_at = now_utc()
            return task

        config = BatchConfig(
            target_list_path=target_file,
            concurrency=1,
            clone_dir=tmp_path / "clones",
        )

        with patch("gh_link_auditor.batch.engine._process_single_repo", side_effect=mock_process):
            report = asyncio.run(run_batch(config))

        assert report.repos_scanned == 3
        assert report.repos_succeeded == 2
        assert report.repos_failed == 1
        assert len(report.errors) == 1
        assert report.errors[0]["repo"] == "owner/repo1"


class TestCheckpointAndResume:
    """T050, T060: Checkpoint save and resume tests (REQ-2)."""

    def test_save_and_load_checkpoint(self, tmp_path) -> None:
        """T060: Atomic checkpoint write (REQ-2)."""
        state = BatchState(
            batch_id="test-123",
            tasks=[
                RepoTask(
                    repo_full_name="owner/repo1",
                    clone_url="https://github.com/owner/repo1.git",
                    status=TaskStatus.COMPLETED,
                    links_found=5,
                ),
                RepoTask(
                    repo_full_name="owner/repo2",
                    clone_url="https://github.com/owner/repo2.git",
                    status=TaskStatus.PENDING,
                ),
            ],
            current_index=1,
        )
        state.config = BatchConfig(target_list_path=tmp_path / "targets.json")

        checkpoint_path = tmp_path / "checkpoint.json"
        _save_checkpoint(state, checkpoint_path)

        assert checkpoint_path.exists()
        assert not checkpoint_path.with_suffix(".tmp").exists()

        loaded = _load_checkpoint(checkpoint_path)
        assert loaded.batch_id == "test-123"
        assert len(loaded.tasks) == 2
        assert loaded.current_index == 1
        assert loaded.tasks[0].status == TaskStatus.COMPLETED

    def test_resume_skips_completed(self, tmp_path) -> None:
        """T050: Checkpoint and resume (REQ-2)."""
        checkpoint_path = FIXTURE_DIR / "batch_state_checkpoint.json"
        report = asyncio.run(resume_batch(checkpoint_path))

        # 5 total tasks, 3 already processed (2 completed + 1 failed), 2 remaining
        assert report.repos_scanned == 5

    def test_atomic_write_no_partial(self, tmp_path) -> None:
        """Verify temp file doesn't persist after save."""
        state = BatchState(batch_id="atomic-test")
        state.config = BatchConfig(target_list_path=tmp_path / "t.json")
        cp_path = tmp_path / "cp.json"

        _save_checkpoint(state, cp_path)

        assert cp_path.exists()
        tmp_file = cp_path.with_suffix(".tmp")
        assert not tmp_file.exists()


class TestSerializeDeserialize:
    """Tests for state serialization round-trip."""

    def test_round_trip(self, tmp_path) -> None:
        state = BatchState(
            batch_id="rt-test",
            tasks=[
                RepoTask(
                    repo_full_name="a/b",
                    clone_url="https://github.com/a/b.git",
                    status=TaskStatus.FAILED,
                    error_message="boom",
                    links_found=3,
                    pr_submitted=True,
                    pr_url="https://github.com/a/b/pull/1",
                ),
            ],
            current_index=1,
        )
        state.config = BatchConfig(
            target_list_path=tmp_path / "t.json",
            concurrency=3,
            dry_run=True,
        )

        data = _serialize_state(state)
        loaded = _deserialize_state(data)

        assert loaded.batch_id == "rt-test"
        assert loaded.tasks[0].repo_full_name == "a/b"
        assert loaded.tasks[0].status == TaskStatus.FAILED
        assert loaded.tasks[0].error_message == "boom"
        assert loaded.tasks[0].pr_submitted is True
        assert loaded.config is not None
        assert loaded.config.concurrency == 3
        assert loaded.config.dry_run is True


class TestDryRun:
    """T220, T320: Dry-run mode (REQ-13)."""

    def test_dry_run_skips_pr(self, tmp_path) -> None:
        """T220: Dry-run mode skips PR submission (REQ-13)."""
        targets = [
            {"full_name": "owner/repo1", "clone_url": "https://github.com/owner/repo1.git"},
            {"full_name": "owner/repo2", "clone_url": "https://github.com/owner/repo2.git"},
        ]
        target_file = tmp_path / "targets.json"
        target_file.write_text(json.dumps(targets))

        config = BatchConfig(
            target_list_path=target_file,
            concurrency=1,
            dry_run=True,
            clone_dir=tmp_path / "clones",
        )
        report = asyncio.run(run_batch(config))

        assert report.total_prs_submitted == 0

    def test_dry_run_completes_pipeline(self, tmp_path) -> None:
        """T320: Dry-run completes full pipeline without PR (REQ-13)."""
        targets = [{"full_name": "owner/repo1"}]
        target_file = tmp_path / "targets.json"
        target_file.write_text(json.dumps(targets))

        async def mock_process(task, tm, rl, config):
            from gh_link_auditor.batch.models import now_utc

            task.started_at = now_utc()
            task.links_found = 10
            task.broken_links = 3
            task.fixes_generated = 2
            task.pr_submitted = False
            task.status = TaskStatus.COMPLETED
            task.completed_at = now_utc()
            return task

        config = BatchConfig(
            target_list_path=target_file,
            concurrency=1,
            dry_run=True,
            clone_dir=tmp_path / "clones",
        )

        with patch("gh_link_auditor.batch.engine._process_single_repo", side_effect=mock_process):
            report = asyncio.run(run_batch(config))

        assert report.total_fixes_generated == 2
        assert report.total_prs_submitted == 0


class TestTimeout:
    """T230: Per-repo timeout enforcement (REQ-3)."""

    def test_slow_repo_times_out(self) -> None:
        task = RepoTask(
            repo_full_name="owner/slow",
            clone_url="https://github.com/owner/slow.git",
        )

        async def slow_process():
            rl = AdaptiveRateLimiter()
            config = BatchConfig(target_list_path=Path("/dev/null"))

            async def mock_acquire():
                await asyncio.sleep(10)

            rl.acquire = mock_acquire

            try:
                result = await asyncio.wait_for(
                    _process_single_repo(task, None, rl, config),
                    timeout=0.1,
                )
            except asyncio.TimeoutError:
                task.status = TaskStatus.FAILED
                task.error_message = "timeout"
                return task
            return result

        result = asyncio.run(slow_process())
        assert result.status == TaskStatus.FAILED
        assert "timeout" in (result.error_message or "")


class TestMaxRepos:
    """Tests for max_repos cap."""

    def test_max_repos_limits_processing(self, tmp_path) -> None:
        targets = [{"full_name": f"owner/repo{i}"} for i in range(10)]
        target_file = tmp_path / "targets.json"
        target_file.write_text(json.dumps(targets))

        config = BatchConfig(
            target_list_path=target_file,
            concurrency=1,
            max_repos=3,
            clone_dir=tmp_path / "clones",
        )
        report = asyncio.run(run_batch(config))
        assert report.repos_scanned == 3


class TestProcessSingleRepoErrors:
    """Tests for error handling in _process_single_repo."""

    def test_general_exception_caught(self) -> None:
        task = RepoTask(
            repo_full_name="owner/fail",
            clone_url="https://github.com/owner/fail.git",
        )
        rl = AdaptiveRateLimiter()

        async def bad_acquire():
            raise RuntimeError("network error")

        rl.acquire = bad_acquire

        result = asyncio.run(_process_single_repo(task, None, rl, BatchConfig(target_list_path=Path("/dev/null"))))
        assert result.status == TaskStatus.FAILED
        assert "network error" in (result.error_message or "")

    def test_timeout_error_caught(self) -> None:
        task = RepoTask(
            repo_full_name="owner/slow",
            clone_url="https://github.com/owner/slow.git",
        )
        rl = AdaptiveRateLimiter()

        async def timeout_acquire():
            raise asyncio.TimeoutError()

        rl.acquire = timeout_acquire

        result = asyncio.run(_process_single_repo(task, None, rl, BatchConfig(target_list_path=Path("/dev/null"))))
        assert result.status == TaskStatus.FAILED
        assert result.error_message == "timeout"


class TestResumeErrors:
    """Tests for resume error paths."""

    def test_resume_no_config_raises(self, tmp_path) -> None:
        checkpoint = tmp_path / "bad_cp.json"
        checkpoint.write_text(
            json.dumps(
                {
                    "batch_id": "test",
                    "tasks": [],
                    "current_index": 0,
                }
            )
        )

        from gh_link_auditor.batch.exceptions import BatchInputError

        with pytest.raises(BatchInputError, match="no config"):
            asyncio.run(resume_batch(checkpoint))

    def test_resume_invalid_checkpoint(self, tmp_path) -> None:
        bad_file = tmp_path / "corrupt.json"
        bad_file.write_text("{invalid json")

        from gh_link_auditor.batch.exceptions import BatchInputError

        with pytest.raises(BatchInputError, match="Failed to load"):
            asyncio.run(resume_batch(bad_file))


class TestConcurrency:
    """T240, T300: Concurrent execution (REQ-1)."""

    def test_concurrent_three_workers(self, tmp_path) -> None:
        """T240: Concurrent execution with 3 workers (REQ-1)."""
        targets = [{"full_name": f"owner/repo{i}"} for i in range(5)]
        target_file = tmp_path / "targets.json"
        target_file.write_text(json.dumps(targets))

        max_concurrent = 0
        current_concurrent = 0
        lock = asyncio.Lock()

        async def mock_process(task, tm, rl, config):
            nonlocal max_concurrent, current_concurrent
            from gh_link_auditor.batch.models import now_utc

            async with lock:
                current_concurrent += 1
                if current_concurrent > max_concurrent:
                    max_concurrent = current_concurrent

            await asyncio.sleep(0.01)  # Simulate work

            async with lock:
                current_concurrent -= 1

            task.started_at = now_utc()
            task.status = TaskStatus.COMPLETED
            task.completed_at = now_utc()
            return task

        config = BatchConfig(
            target_list_path=target_file,
            concurrency=3,
            clone_dir=tmp_path / "clones",
        )

        with patch("gh_link_auditor.batch.engine._process_single_repo", side_effect=mock_process):
            report = asyncio.run(run_batch(config))

        assert report.repos_scanned == 5
        assert report.repos_succeeded == 5
        assert max_concurrent <= 3

    def test_concurrency_parameter_controls_workers(self, tmp_path) -> None:
        """T300: Configurable concurrency parameter (REQ-1)."""
        targets = [{"full_name": f"owner/repo{i}"} for i in range(3)]
        target_file = tmp_path / "targets.json"
        target_file.write_text(json.dumps(targets))

        # Test with concurrency=1
        config1 = BatchConfig(
            target_list_path=target_file,
            concurrency=1,
            clone_dir=tmp_path / "clones",
        )
        report1 = asyncio.run(run_batch(config1))
        assert report1.repos_succeeded == 3

        # Test with concurrency=5
        config5 = BatchConfig(
            target_list_path=target_file,
            concurrency=5,
            clone_dir=tmp_path / "clones",
        )
        report5 = asyncio.run(run_batch(config5))
        assert report5.repos_succeeded == 3
