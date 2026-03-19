"""Repo quality assessment and contributing guidelines reader.

Fetches repo metadata (stars, recency, contributors) and contribution
guidelines to assess whether a repo is a good PR target.

See Issues #98, #99 for specification.
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class RepoQuality:
    """Quality metrics for a target repository."""

    stars: int = 0
    pushed_at: str = ""
    contributors: int = 0
    contributing_text: str = ""
    warnings: list[str] | None = None

    def __post_init__(self) -> None:
        if self.warnings is None:
            self.warnings = []


def fetch_repo_metadata(owner: str, repo: str) -> RepoQuality:
    """Fetch repo quality metrics from GitHub API.

    Args:
        owner: Repository owner.
        repo: Repository name.

    Returns:
        RepoQuality with stars, pushed_at, and contributor count.
    """
    quality = RepoQuality()

    # Fetch repo details
    try:
        result = subprocess.run(
            [
                "gh",
                "api",
                f"repos/{owner}/{repo}",
                "--jq",
                "{stars: .stargazers_count, pushed_at: .pushed_at}",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode == 0:
            import json

            data = json.loads(result.stdout)
            quality.stars = data.get("stars", 0)
            quality.pushed_at = data.get("pushed_at", "")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        logger.warning("Failed to fetch repo metadata for %s/%s", owner, repo)

    # Fetch contributor count (from pagination header)
    try:
        result = subprocess.run(
            [
                "gh",
                "api",
                f"repos/{owner}/{repo}/contributors",
                "--jq",
                "length",
                "-q",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode == 0:
            count_str = result.stdout.strip()
            if count_str.isdigit():
                quality.contributors = int(count_str)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return quality


def fetch_contributing_guidelines(owner: str, repo: str) -> str:
    """Fetch CONTRIBUTING.md content from common locations.

    Checks: root, .github/, docs/.

    Args:
        owner: Repository owner.
        repo: Repository name.

    Returns:
        Contributing guidelines text, or empty string if not found.
    """
    paths = ["CONTRIBUTING.md", ".github/CONTRIBUTING.md", "docs/CONTRIBUTING.md"]

    for path in paths:
        try:
            result = subprocess.run(
                [
                    "gh",
                    "api",
                    f"repos/{owner}/{repo}/contents/{path}",
                    "--jq",
                    ".content",
                ],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                import base64

                content = base64.b64decode(result.stdout.strip()).decode("utf-8", errors="replace")
                return content
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    return ""


def analyze_contributing_guidelines(text: str) -> list[str]:
    """Analyze contributing guidelines for potential issues.

    Flags patterns that suggest our automated PR approach may be rejected.

    Args:
        text: Contributing guidelines text.

    Returns:
        List of warning strings.
    """
    if not text:
        return []

    warnings: list[str] = []
    text_lower = text.lower()

    # Discussion-first requirement
    if re.search(r"start.{0,20}(with|as).{0,20}discussion", text_lower):
        warnings.append("Repo prefers discussion before PRs")

    if "discussion" in text_lower and "before" in text_lower:
        if "Repo prefers discussion before PRs" not in warnings:
            warnings.append("Repo prefers discussion before PRs")

    # No bot/automated contributions
    if re.search(r"no.{0,10}(bot|automated|auto)", text_lower):
        warnings.append("Repo may reject automated contributions")

    # CLA requirement
    if re.search(r"(contributor.{0,10}license|cla|sign.{0,10}agreement)", text_lower):
        warnings.append("Repo requires CLA signing")

    return warnings


def format_quality_summary(quality: RepoQuality) -> str:
    """Format repo quality as a brief summary line.

    Args:
        quality: RepoQuality data.

    Returns:
        Human-readable summary string.
    """
    parts = []
    if quality.stars:
        parts.append(f"{quality.stars:,} stars")
    if quality.contributors:
        parts.append(f"{quality.contributors} contributors")
    if quality.pushed_at:
        parts.append(f"last push {quality.pushed_at[:10]}")

    return " | ".join(parts) if parts else "no metadata available"
