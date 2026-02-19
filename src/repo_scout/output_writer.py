"""Output writer for Repo Scout results.

See LLD #3 §2.4 for output_writer specification.
"""

from __future__ import annotations

import json
from pathlib import Path

from repo_scout.models import RepositoryRecord


def format_for_docfix_bot(repos: list[RepositoryRecord]) -> list[str]:
    """Format repos as simple owner/repo list for Doc-Fix Bot.

    Args:
        repos: List of RepositoryRecords.

    Returns:
        List of "owner/repo" strings.
    """
    return [r["full_name"] for r in repos]


def write_output(
    repos: list[RepositoryRecord],
    output_path: str,
    fmt: str = "json",
) -> int:
    """Write deduplicated repos to file.

    Args:
        repos: List of RepositoryRecords.
        output_path: Path to output file.
        fmt: Output format ("json", "jsonl", or "txt").

    Returns:
        Count of repos written.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "json":
        path.write_text(json.dumps(repos, indent=2, default=str))
    elif fmt == "jsonl":
        lines = [json.dumps(r, default=str) for r in repos]
        path.write_text("\n".join(lines) + "\n")
    elif fmt == "txt":
        names = format_for_docfix_bot(repos)
        path.write_text("\n".join(names) + "\n")
    else:
        msg = f"Unknown output format: {fmt}"
        raise ValueError(msg)

    return len(repos)
