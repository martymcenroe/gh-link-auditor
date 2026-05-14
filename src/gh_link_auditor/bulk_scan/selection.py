"""Stage 0 — select 7,500 active Python doc repos via GitHub Search (#218).

Search API limit: 30 req/min, 1000 results per query, 5K total results per
query string. We slice the universe by star ranges to dodge the 1000-result
hard ceiling.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from typing import Any

from gh_link_auditor.bulk_scan.config import (
    MAX_STARS,
    MIN_STARS,
    PUSHED_WITHIN_DAYS,
)

logger = logging.getLogger(__name__)


# Star-range slices to dodge GitHub Search's 1000-result-per-query ceiling.
# Each slice yields ≤1000 repos; we pull all slices and dedup.
DEFAULT_STAR_SLICES: list[tuple[int, int]] = [
    (100, 150),
    (150, 200),
    (200, 250),
    (250, 300),
    (300, 400),
    (400, 500),
    (500, 700),
    (700, 1000),
    (1000, 1500),
    (1500, 2500),
    (2500, 5000),
    (5000, 10000),
]


def _pushed_since(days_ago: int) -> str:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return cutoff.strftime("%Y-%m-%d")


def _gh_search_one_slice(
    stars_low: int,
    stars_high: int,
    pushed_since: str,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """Search GitHub for one star-range slice. Returns repo metadata."""
    query = (
        f"language:Python stars:{stars_low}..{stars_high} pushed:>{pushed_since} archived:false is:public NOT fork:true"
    )
    cmd = [
        "gh",
        "search",
        "repos",
        query,
        "--limit",
        str(limit),
        "--json",
        "fullName,stargazersCount,pushedAt,isArchived,visibility",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=120)
        return json.loads(result.stdout)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        logger.warning("gh search failed for slice %s-%s: %s", stars_low, stars_high, e)
        return []


def select_python_repos(
    target_count: int,
    star_slices: list[tuple[int, int]] | None = None,
    blacklisted_repos: set[str] | None = None,
    inter_request_sleep_s: float = 2.0,
) -> Iterator[dict[str, Any]]:
    """Yield deduplicated repo dicts up to target_count.

    Args:
        target_count: How many repos to yield (stops when reached).
        star_slices: Override the default slice list (mostly for tests).
        blacklisted_repos: Set of repo full names to skip.
        inter_request_sleep_s: Sleep between gh-search calls (Search API rate limit).

    Yields:
        Dicts with keys ``full_name``, ``stars``, ``pushed_at``.
    """
    if star_slices is None:
        star_slices = DEFAULT_STAR_SLICES
    if blacklisted_repos is None:
        blacklisted_repos = set()

    pushed_since = _pushed_since(PUSHED_WITHIN_DAYS)
    seen: set[str] = set()
    yielded = 0

    for low, high in star_slices:
        if yielded >= target_count:
            return
        repos = _gh_search_one_slice(low, high, pushed_since)
        logger.info("selection: slice %d..%d returned %d repos", low, high, len(repos))
        for r in repos:
            if yielded >= target_count:
                return
            full_name = r.get("fullName") or ""
            if not full_name or full_name in seen or full_name in blacklisted_repos:
                continue
            stars = r.get("stargazersCount") or 0
            if stars < MIN_STARS or stars > MAX_STARS:
                continue
            if r.get("isArchived"):
                continue
            seen.add(full_name)
            yielded += 1
            yield {
                "full_name": full_name,
                "stars": stars,
                "pushed_at": r.get("pushedAt"),
            }
        time.sleep(inter_request_sleep_s)
