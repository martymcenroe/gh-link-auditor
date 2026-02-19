"""Repository target management.

See LLD #2 §2.4 for target_manager specification.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from docfix_bot.models import TargetRepository

logger = logging.getLogger(__name__)


def load_targets(config_path: Path) -> list[TargetRepository]:
    """Load and validate repository targets from YAML.

    Args:
        config_path: Path to targets.yaml.

    Returns:
        List of TargetRepository dicts.

    Raises:
        ValueError: If YAML is invalid or missing required fields.
    """
    if not config_path.exists():
        msg = f"Targets file not found: {config_path}"
        raise ValueError(msg)

    content = config_path.read_text()
    data = yaml.safe_load(content)

    if not isinstance(data, dict) or "repositories" not in data:
        msg = "Invalid targets YAML: missing 'repositories' key"
        raise ValueError(msg)

    repos = data["repositories"]
    if not isinstance(repos, list):
        msg = "Invalid targets YAML: 'repositories' must be a list"
        raise ValueError(msg)

    targets: list[TargetRepository] = []
    for entry in repos:
        if not isinstance(entry, dict):
            continue
        if "owner" not in entry or "repo" not in entry:
            logger.warning("Skipping invalid target entry: %s", entry)
            continue
        targets.append(
            TargetRepository(
                owner=entry["owner"],
                repo=entry["repo"],
                priority=entry.get("priority", 5),
                last_scanned=entry.get("last_scanned"),
                enabled=entry.get("enabled", True),
            )
        )

    return targets


def prioritize_targets(
    targets: list[TargetRepository],
) -> list[TargetRepository]:
    """Sort targets by priority (desc) then least recently scanned.

    Disabled targets are filtered out.

    Args:
        targets: List of TargetRepository dicts.

    Returns:
        Sorted and filtered list.
    """
    enabled = [t for t in targets if t["enabled"]]
    return sorted(
        enabled,
        key=lambda t: (
            -t["priority"],
            t["last_scanned"] or "",
        ),
    )


def is_blocklisted(
    target: TargetRepository,
    blocklist_path: Path,
) -> bool:
    """Check if a repository is in the manual blocklist.

    Args:
        target: Repository to check.
        blocklist_path: Path to blocklist.yaml.

    Returns:
        True if blocklisted.
    """
    if not blocklist_path.exists():
        return False

    content = blocklist_path.read_text()
    data = yaml.safe_load(content)

    if not isinstance(data, dict) or "blocked" not in data:
        return False

    blocked = data["blocked"]
    if not isinstance(blocked, list):
        return False

    full_name = f"{target['owner']}/{target['repo']}"
    return full_name in blocked


def check_contributing_md(repo_path: Path) -> bool:
    """Check if CONTRIBUTING.md allows bot contributions.

    Args:
        repo_path: Path to cloned repository.

    Returns:
        True if contributions are allowed (or no CONTRIBUTING.md).
    """
    contributing = repo_path / "CONTRIBUTING.md"
    if not contributing.exists():
        return True  # No file = no restrictions

    content = contributing.read_text().lower()
    # Check for explicit bot rejection phrases
    reject_phrases = [
        "no bots",
        "no automated",
        "bot contributions not accepted",
        "automated prs not accepted",
        "do not submit automated",
    ]
    return not any(phrase in content for phrase in reject_phrases)
