"""N5 Generate Fix node.

Generates unified diff patches for approved replacements.

See LLD #22 §2.4 for n5_generate_fix specification.
"""

from __future__ import annotations

import difflib
import logging
from pathlib import Path

from gh_link_auditor.pipeline.state import FixPatch, PipelineState

logger = logging.getLogger(__name__)


def generate_unified_diff(
    file_path: str,
    original_url: str,
    replacement_url: str,
) -> str:
    """Generate unified diff for a single URL replacement.

    Args:
        file_path: Path to the file containing the URL.
        original_url: URL to replace.
        replacement_url: New URL.

    Returns:
        Unified diff string, or empty string if no changes.
    """
    try:
        content = Path(file_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        logger.warning("Cannot read file: %s", file_path)
        return ""

    if original_url not in content:
        return ""

    new_content = content.replace(original_url, replacement_url)

    original_lines = content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)

    diff_lines = list(
        difflib.unified_diff(
            original_lines,
            new_lines,
            fromfile=f"a/{Path(file_path).name}",
            tofile=f"b/{Path(file_path).name}",
        )
    )

    if not diff_lines:
        return ""

    return "".join(diff_lines)


def n5_generate_fix(state: PipelineState) -> PipelineState:
    """N5 node: Generate fix patches for approved replacements.

    For each approved verdict with a candidate, generates a unified diff.

    Args:
        state: Current pipeline state.

    Returns:
        Updated PipelineState with fixes populated.
    """
    reviewed = state.get("reviewed_verdicts", [])
    fixes: list[FixPatch] = []

    for verdict in reviewed:
        if not verdict.get("approved"):
            continue

        candidate = verdict.get("candidate")
        if not candidate:
            continue

        dead_link = verdict["dead_link"]
        source_file = dead_link["source_file"]
        original_url = dead_link["url"]
        replacement_url = candidate["url"]

        diff = generate_unified_diff(source_file, original_url, replacement_url)
        if diff:
            fixes.append(
                FixPatch(
                    source_file=source_file,
                    original_url=original_url,
                    replacement_url=replacement_url,
                    unified_diff=diff,
                )
            )

    state["fixes"] = fixes
    return state
