"""Pipeline state management.

Defines PipelineState TypedDict and utilities for creating,
persisting, and loading state.

See LLD #22 §2.3 for PipelineState specification.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict


class DeadLink(TypedDict):
    """A single dead link discovered during scan."""

    url: str
    source_file: str
    line_number: int
    link_text: str
    http_status: int | None
    error_type: str


class ReplacementCandidate(TypedDict):
    """A potential replacement URL for a dead link."""

    url: str
    source: str
    title: str | None
    snippet: str | None


class Verdict(TypedDict):
    """Mr. Slant's judgment on a replacement candidate."""

    dead_link: DeadLink
    candidate: ReplacementCandidate | None
    confidence: float
    reasoning: str
    approved: bool | None


class FixPatch(TypedDict):
    """A generated fix for a dead link."""

    source_file: str
    original_url: str
    replacement_url: str
    unified_diff: str


class CostRecord(TypedDict):
    """Cost tracking for a single LLM call."""

    node: str
    model: str
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    timestamp: str


class PipelineState(TypedDict, total=False):
    """Complete state passed between pipeline nodes."""

    # Input
    target: str
    target_type: str  # "url" or "local"
    repo_name: str

    # Configuration
    max_links: int
    max_cost_usd: float
    confidence_threshold: float
    dry_run: bool
    verbose: bool

    # N0 Output
    doc_files: list[str]

    # N1 Output
    dead_links: list[DeadLink]
    scan_complete: bool

    # Circuit Breaker
    circuit_breaker_triggered: bool

    # N2 Output
    candidates: dict[str, list[ReplacementCandidate]]

    # N3 Output
    verdicts: list[Verdict]

    # N4 Output
    reviewed_verdicts: list[Verdict]

    # N5 Output
    fixes: list[FixPatch]

    # Cost Tracking
    cost_records: list[CostRecord]
    total_cost_usd: float
    cost_limit_reached: bool

    # Error Handling
    errors: list[str]
    partial_results: bool

    # Persistence
    run_id: str
    db_path: str


def create_initial_state(
    target: str,
    max_links: int = 50,
    max_cost_usd: float = 5.00,
    confidence_threshold: float = 0.8,
    dry_run: bool = False,
    verbose: bool = False,
    db_path: str | None = None,
) -> PipelineState:
    """Create initial pipeline state from CLI inputs.

    Args:
        target: Repository URL or local path.
        max_links: Circuit breaker threshold.
        max_cost_usd: Cost limit in USD.
        confidence_threshold: Min confidence for auto-approval.
        dry_run: Skip N4/N5 if True.
        verbose: Detailed logging.
        db_path: Path to SQLite state database.

    Returns:
        Initialized PipelineState.
    """
    run_id = str(uuid.uuid4())
    if db_path is None:
        db_path = str(Path.home() / ".ghla" / "state.db")

    return PipelineState(
        target=target,
        target_type="",
        repo_name="",
        max_links=max_links,
        max_cost_usd=max_cost_usd,
        confidence_threshold=confidence_threshold,
        dry_run=dry_run,
        verbose=verbose,
        doc_files=[],
        dead_links=[],
        scan_complete=False,
        circuit_breaker_triggered=False,
        candidates={},
        verdicts=[],
        reviewed_verdicts=[],
        fixes=[],
        cost_records=[],
        total_cost_usd=0.0,
        cost_limit_reached=False,
        errors=[],
        partial_results=False,
        run_id=run_id,
        db_path=db_path,
    )


def persist_state(state: PipelineState, node_name: str) -> None:
    """Persist current state to JSON file after node completion.

    Args:
        state: Current pipeline state.
        node_name: Name of the completed node.
    """
    db_path = Path(state.get("db_path", ""))
    if not db_path or str(db_path) == ".":
        return

    state_dir = db_path.parent
    state_dir.mkdir(parents=True, exist_ok=True)

    state_file = state_dir / f"{state['run_id']}.json"
    record = {
        "run_id": state["run_id"],
        "last_node": node_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "state": dict(state),
    }
    state_file.write_text(json.dumps(record, indent=2, default=str))


def load_state(run_id: str, db_path: str) -> PipelineState | None:
    """Load state from previous run for resumption.

    Args:
        run_id: UUID of the pipeline run.
        db_path: Path to state database.

    Returns:
        Loaded PipelineState, or None if not found.
    """
    state_dir = Path(db_path).parent
    state_file = state_dir / f"{run_id}.json"

    if not state_file.exists():
        return None

    data = json.loads(state_file.read_text())
    return data.get("state")
