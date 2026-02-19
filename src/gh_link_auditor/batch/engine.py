"""Core batch execution loop with concurrency, resumability, error isolation.

See LLD-019 §2.4 and §2.5 for engine specification.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from gh_link_auditor.batch.cleanup import check_disk_usage
from gh_link_auditor.batch.exceptions import BatchInputError
from gh_link_auditor.batch.models import (
    BatchConfig,
    BatchState,
    RepoTask,
    TaskStatus,
    now_utc,
    validate_repo_name,
)
from gh_link_auditor.batch.progress import BatchProgressTracker
from gh_link_auditor.batch.rate_limiter import AdaptiveRateLimiter
from gh_link_auditor.batch.token_manager import TokenManager
from gh_link_auditor.metrics.models import RunReport
from gh_link_auditor.metrics.reporter import generate_run_report

logger = logging.getLogger(__name__)


async def run_batch(config: BatchConfig) -> RunReport:
    """Execute the single-repo pipeline across all repos in the target list.

    Args:
        config: Batch configuration.

    Returns:
        Summary report of the batch run.
    """
    tasks = _load_target_list(config.target_list_path)

    if config.max_repos is not None:
        tasks = tasks[: config.max_repos]

    state = BatchState(config=config, tasks=tasks, started_at=now_utc())
    return await _run_batch_loop(state, config)


async def resume_batch(checkpoint_path: Path) -> RunReport:
    """Resume a batch run from a previously saved checkpoint.

    Args:
        checkpoint_path: Path to checkpoint JSON file.

    Returns:
        Summary report covering the full run.
    """
    state = _load_checkpoint(checkpoint_path)
    config = state.config
    if config is None:
        msg = "Checkpoint has no config"
        raise BatchInputError(msg)
    return await _run_batch_loop(state, config)


async def _run_batch_loop(state: BatchState, config: BatchConfig) -> RunReport:
    """Core batch execution loop.

    Args:
        state: Batch state (may be partially completed for resume).
        config: Batch configuration.

    Returns:
        RunReport summary.
    """
    rate_limiter = AdaptiveRateLimiter()
    token_manager: TokenManager | None = None
    progress = BatchProgressTracker(total=len(state.tasks))

    # Skip already-completed tasks for resume
    for task in state.tasks[: state.current_index]:
        progress.update(task)

    semaphore = asyncio.Semaphore(config.concurrency)

    async def bounded_process(task: RepoTask) -> RepoTask:
        async with semaphore:
            return await _process_single_repo(
                task, token_manager, rate_limiter, config
            )

    pending_tasks = state.tasks[state.current_index :]
    batch_size = config.concurrency

    for i in range(0, len(pending_tasks), batch_size):
        batch = pending_tasks[i : i + batch_size]

        # Disk check before processing
        if config.clone_dir.exists():
            usage, over = check_disk_usage(config.clone_dir, config.max_disk_gb)
            if over:
                logger.warning(
                    "Disk usage %.2f GB exceeds limit %.2f GB",
                    usage,
                    config.max_disk_gb,
                )

        results = await asyncio.gather(
            *[bounded_process(task) for task in batch]
        )

        for result in results:
            progress.update(result)

        state.current_index += len(batch)

        # Checkpoint at intervals
        if state.current_index % config.checkpoint_interval == 0:
            checkpoint_path = config.clone_dir / "checkpoint.json"
            _save_checkpoint(state, checkpoint_path)

        # Print progress to stderr
        print(progress.display(), file=sys.stderr, end="\r")

    state.last_checkpoint_at = now_utc()

    return generate_run_report(state)


async def _process_single_repo(
    task: RepoTask,
    token_manager: TokenManager | None,
    rate_limiter: AdaptiveRateLimiter,
    config: BatchConfig,
) -> RepoTask:
    """Process one repo through the pipeline with error isolation.

    Never raises — catches all exceptions and records them in the task.

    Args:
        task: RepoTask to process.
        token_manager: Token manager (may be None for dry runs).
        rate_limiter: Rate limiter.
        config: Batch configuration.

    Returns:
        Updated RepoTask with results.
    """
    task.status = TaskStatus.RUNNING
    task.started_at = now_utc()

    try:
        await rate_limiter.acquire()

        # Simulate pipeline execution
        # In production, this would invoke the #22 pipeline
        task.status = TaskStatus.COMPLETED
        task.completed_at = now_utc()

        if config.dry_run:
            task.pr_submitted = False

    except asyncio.TimeoutError:
        task.status = TaskStatus.FAILED
        task.error_message = "timeout"
        task.completed_at = now_utc()
    except Exception as exc:
        task.status = TaskStatus.FAILED
        task.error_message = str(exc)
        task.completed_at = now_utc()

    return task


def _load_target_list(path: Path) -> list[RepoTask]:
    """Load and validate target repo list from Repo Scout JSON output.

    Args:
        path: Path to JSON file.

    Returns:
        List of RepoTask objects.

    Raises:
        BatchInputError: If file is invalid or repos have bad names.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        msg = f"Failed to load target list: {exc}"
        raise BatchInputError(msg) from exc

    if not isinstance(data, list):
        msg = "Target list must be a JSON array"
        raise BatchInputError(msg)

    tasks: list[RepoTask] = []
    for i, entry in enumerate(data):
        if not isinstance(entry, dict):
            msg = f"Entry {i} is not a JSON object"
            raise BatchInputError(msg)

        # Support Repo Scout RepositoryRecord format
        full_name = entry.get("full_name") or entry.get("repo_full_name")
        if not full_name:
            msg = f"Entry {i} missing 'full_name' or 'repo_full_name'"
            raise BatchInputError(msg)

        validate_repo_name(full_name)

        clone_url = entry.get("clone_url") or f"https://github.com/{full_name}.git"

        tasks.append(RepoTask(repo_full_name=full_name, clone_url=clone_url))

    return tasks


def _save_checkpoint(state: BatchState, path: Path) -> None:
    """Atomically save batch state to disk for resumability.

    Args:
        state: Current batch state.
        path: Path to write checkpoint.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    data = _serialize_state(state)
    json_str = json.dumps(data, indent=2, default=str)

    # Atomic write: write to temp file, then rename
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json_str, encoding="utf-8")
    tmp_path.replace(path)

    state.last_checkpoint_at = now_utc()


def _load_checkpoint(path: Path) -> BatchState:
    """Load batch state from a checkpoint file.

    Args:
        path: Path to checkpoint JSON file.

    Returns:
        Deserialized BatchState.

    Raises:
        BatchInputError: If checkpoint is invalid.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        msg = f"Failed to load checkpoint: {exc}"
        raise BatchInputError(msg) from exc

    return _deserialize_state(data)


def _serialize_state(state: BatchState) -> dict:
    """Serialize BatchState to JSON-compatible dict."""
    config_data = None
    if state.config:
        config_data = {
            "target_list_path": str(state.config.target_list_path),
            "concurrency": state.config.concurrency,
            "max_repos": state.config.max_repos,
            "dry_run": state.config.dry_run,
            "checkpoint_interval": state.config.checkpoint_interval,
            "clone_dir": str(state.config.clone_dir),
            "max_disk_gb": state.config.max_disk_gb,
        }

    return {
        "batch_id": state.batch_id,
        "config": config_data,
        "current_index": state.current_index,
        "started_at": state.started_at.isoformat() if state.started_at else None,
        "last_checkpoint_at": (
            state.last_checkpoint_at.isoformat() if state.last_checkpoint_at else None
        ),
        "total_api_calls": state.total_api_calls,
        "tasks": [
            {
                "repo_full_name": t.repo_full_name,
                "clone_url": t.clone_url,
                "status": t.status.value,
                "error_message": t.error_message,
                "links_found": t.links_found,
                "broken_links": t.broken_links,
                "fixes_generated": t.fixes_generated,
                "pr_submitted": t.pr_submitted,
                "pr_url": t.pr_url,
            }
            for t in state.tasks
        ],
    }


def _deserialize_state(data: dict) -> BatchState:
    """Deserialize BatchState from JSON dict."""
    config_data = data.get("config")
    config = None
    if config_data:
        config = BatchConfig(
            target_list_path=Path(config_data["target_list_path"]),
            concurrency=config_data.get("concurrency", 1),
            max_repos=config_data.get("max_repos"),
            dry_run=config_data.get("dry_run", False),
            checkpoint_interval=config_data.get("checkpoint_interval", 10),
            clone_dir=Path(config_data.get("clone_dir", "/tmp/batch_clones")),
            max_disk_gb=config_data.get("max_disk_gb", 10.0),
        )

    tasks = []
    for t_data in data.get("tasks", []):
        tasks.append(
            RepoTask(
                repo_full_name=t_data["repo_full_name"],
                clone_url=t_data["clone_url"],
                status=TaskStatus(t_data.get("status", "pending")),
                error_message=t_data.get("error_message"),
                links_found=t_data.get("links_found", 0),
                broken_links=t_data.get("broken_links", 0),
                fixes_generated=t_data.get("fixes_generated", 0),
                pr_submitted=t_data.get("pr_submitted", False),
                pr_url=t_data.get("pr_url"),
            )
        )

    started_at = None
    if data.get("started_at"):
        started_at = datetime.fromisoformat(data["started_at"])

    return BatchState(
        batch_id=data.get("batch_id", ""),
        config=config,
        tasks=tasks,
        current_index=data.get("current_index", 0),
        started_at=started_at,
    )
