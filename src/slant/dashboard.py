"""HITL dashboard for Slant verdict review.

Local HTTP server for reviewing and deciding on uncertain verdicts.
Full implementation in Step 5b (Issue #21 Part 2).

See LLD #21 §2.5 "Dashboard Flow" for specification.
"""

from __future__ import annotations

from pathlib import Path


def start_dashboard(verdicts_path: Path, port: int = 8913) -> None:
    """Start HITL dashboard HTTP server.

    Args:
        verdicts_path: Path to verdicts JSON file.
        port: Port to bind to (default: 8913).
    """
    raise NotImplementedError("Dashboard implementation is in Step 5b")
