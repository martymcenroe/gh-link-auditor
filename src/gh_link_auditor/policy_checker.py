"""Maintainer policy checker for gh-link-auditor.

Checks repository CONTRIBUTING.md files for policy keywords that indicate
whether automated PRs are welcome. See LLD #4 for design rationale.

Deviations from LLD-004:
- Synchronous (not async) to match the rest of the codebase.
- Data structures kept in this module (not split into models/policy.py
  and constants.py) to avoid over-engineering for a small module.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from enum import Enum
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from gh_link_auditor.state_db import StateDatabase

from src.logging_config import setup_logging

logger = setup_logging("policy_checker")


# ---------------------------------------------------------------------------
# Data structures (LLD §2.3)
# ---------------------------------------------------------------------------


class PolicyKeyword(Enum):
    """Keywords recognised in CONTRIBUTING.md files."""

    NO_BOT = "no-bot"
    NO_PR = "no-pr"
    TYPOS_WELCOME = "typos-welcome"
    SKIP_DOC_PRS = "skip-doc-prs"
    CONTACT_FIRST = "contact-first"


class PolicyStatus(Enum):
    """Outcome of a policy check."""

    ALLOWED = "allowed"
    BLOCKED = "policy-blacklisted"
    UNKNOWN = "unknown"


class PolicyCheckResult(TypedDict):
    """Result of checking a repository's contribution policy."""

    repo_url: str
    contributing_found: bool
    contributing_path: str | None
    keywords_found: list[PolicyKeyword]
    is_blocked: bool
    block_reason: str | None
    status: PolicyStatus


# Keywords that cause a repository to be blocked.
_BLOCKING_KEYWORDS = frozenset(
    {
        PolicyKeyword.NO_BOT,
        PolicyKeyword.NO_PR,
        PolicyKeyword.SKIP_DOC_PRS,
        PolicyKeyword.CONTACT_FIRST,
    }
)

# Locations to check for CONTRIBUTING.md (in priority order).
_CONTRIBUTING_PATHS = [
    "CONTRIBUTING.md",
    ".github/CONTRIBUTING.md",
    "docs/CONTRIBUTING.md",
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _fetch_raw_url(url: str) -> str | None:
    """Fetch raw text content from a URL.

    Returns the content as a string, or ``None`` if the URL returns
    a non-2xx status or a network error occurs.
    """
    try:
        req = urllib.request.Request(
            url,
            method="GET",
            headers={
                "User-Agent": "gh-link-auditor/0.1 policy-checker",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            if 200 <= resp.status < 400:
                return resp.read().decode("utf-8", errors="replace")
    except (urllib.error.HTTPError, urllib.error.URLError, OSError):
        pass
    return None


# ---------------------------------------------------------------------------
# Public API (LLD §2.4)
# ---------------------------------------------------------------------------


def parse_policy_keywords(content: str) -> list[PolicyKeyword]:
    """Parse CONTRIBUTING.md content for policy keywords.

    Uses case-insensitive matching for all defined keywords.

    Args:
        content: Raw text content of a CONTRIBUTING.md file.

    Returns:
        List of matched ``PolicyKeyword`` values (may be empty).
    """
    found: list[PolicyKeyword] = []
    lower = content.lower()
    for kw in PolicyKeyword:
        if re.search(re.escape(kw.value), lower):
            found.append(kw)
    return found


def determine_block_status(
    keywords: list[PolicyKeyword],
) -> tuple[bool, str | None]:
    """Determine if a repository should be blocked based on keywords found.

    Blocking keywords take precedence over welcoming keywords.

    Args:
        keywords: List of keywords found in CONTRIBUTING.md.

    Returns:
        Tuple of ``(is_blocked, reason)``. ``reason`` is ``None`` when
        not blocked.
    """
    for kw in keywords:
        if kw in _BLOCKING_KEYWORDS:
            return True, f"{kw.value} policy"
    return False, None


def fetch_contributing_content(repo_url: str) -> str | None:
    """Fetch CONTRIBUTING.md content from a GitHub repository.

    Tries multiple standard locations (root, ``.github/``, ``docs/``).
    Returns content from the first location found, or ``None`` if the
    file does not exist in any location.

    Args:
        repo_url: GitHub repository URL (e.g. ``https://github.com/org/repo``).

    Returns:
        File content as a string, or ``None`` if not found.
    """
    # Normalise repo URL: strip trailing slash, extract owner/repo
    repo_url = repo_url.rstrip("/")
    # Convert https://github.com/org/repo to raw content base URL
    parts = repo_url.replace("https://github.com/", "").split("/")
    if len(parts) < 2:
        logger.warning("Invalid repo URL format: %s", repo_url)
        return None
    owner, repo = parts[0], parts[1]
    base = f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD"

    for path in _CONTRIBUTING_PATHS:
        url = f"{base}/{path}"
        content = _fetch_raw_url(url)
        if content is not None:
            logger.info("Found %s for %s/%s", path, owner, repo)
            return content

    logger.info("No CONTRIBUTING.md found for %s/%s", owner, repo)
    return None


def check_repository_policy(repo_url: str) -> PolicyCheckResult:
    """Check a repository's contribution policy before scanning.

    Fetches CONTRIBUTING.md, parses for policy keywords, and returns
    a structured result indicating whether the bot should proceed.

    Args:
        repo_url: GitHub repository URL.

    Returns:
        A ``PolicyCheckResult`` with block status and metadata.
    """
    content = fetch_contributing_content(repo_url)

    if content is None:
        return PolicyCheckResult(
            repo_url=repo_url,
            contributing_found=False,
            contributing_path=None,
            keywords_found=[],
            is_blocked=False,
            block_reason=None,
            status=PolicyStatus.UNKNOWN,
        )

    keywords = parse_policy_keywords(content)
    is_blocked, reason = determine_block_status(keywords)

    if is_blocked:
        status = PolicyStatus.BLOCKED
    else:
        status = PolicyStatus.ALLOWED

    return PolicyCheckResult(
        repo_url=repo_url,
        contributing_found=True,
        contributing_path="CONTRIBUTING.md",
        keywords_found=keywords,
        is_blocked=is_blocked,
        block_reason=reason,
        status=status,
    )


def log_policy_result(result: PolicyCheckResult, db: StateDatabase) -> None:
    """Log a policy check result to the state database.

    If the repository is blocked, adds it to the blacklist with reason
    ``"policy-blacklisted"``.

    Args:
        result: The policy check result to log.
        db: State database instance.
    """
    if result["is_blocked"]:
        reason = result["block_reason"] or "policy-blacklisted"
        db.add_to_blacklist(repo_url=result["repo_url"], reason=reason)
        logger.info(
            "Blacklisted %s: %s",
            result["repo_url"],
            reason,
        )
    else:
        logger.info(
            "Policy check passed for %s (status: %s)",
            result["repo_url"],
            result["status"].value,
        )
