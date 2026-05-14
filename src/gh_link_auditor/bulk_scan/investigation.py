"""Stage 3 — investigate confirmed-dead URLs; emit tier-1 candidates (#218).

Wraps LinkDetective for the candidate generation. Filters to tier-1 only
(verified-live, safe methods) per the bulk-run spec.
"""

from __future__ import annotations

import logging
from typing import Any

from gh_link_auditor.bulk_scan.config import TIER1_ONLY_MODE
from gh_link_auditor.pipeline.nodes.n2_investigate import classify_tier

logger = logging.getLogger(__name__)

# Methods we count as tier-1 in this bulk run (#218):
# - redirect_chain — old URL 30x to new URL (suppressed by #197 — see filter below)
# - url_mutation — non-trivial mutation lands on a live page
# - strip_index — trailing /index removed yields a live page
# - wikipedia_suggest — Wikipedia's own redirect API points elsewhere
# - github_api_redirect — GitHub renames detected via API
# Sitemap_search NOT tier-1 by default — included only when sitemap match
# verified live AND shares a significant URL token (handled below).
TIER1_METHODS = {
    "url_mutation",
    "strip_index",
    "wikipedia_suggest",
    "github_api_redirect",
}


def investigate_one(dead_url: str, http_status: int | str) -> list[dict[str, Any]]:
    """Run LinkDetective on one dead URL; return ALL candidate dicts.

    Filtering happens in :func:`filter_tier1` after this returns, so callers
    can also see tier-2 candidates if they want to store them.
    """
    try:
        from gh_link_auditor.link_detective import LinkDetective

        detective = LinkDetective()
        report = detective.investigate(dead_url, http_status)
    except Exception as e:
        logger.debug("investigate failed: %s :: %s", dead_url, e)
        return []

    cands: list[dict[str, Any]] = []
    for cr in report.investigation.candidate_replacements:
        method_str = cr.method.value if hasattr(cr.method, "value") else str(cr.method)
        if method_str == "archive_only":
            continue
        verified = getattr(cr, "verified_live", False)
        tier = classify_tier(method_str, verified)
        cands.append(
            {
                "candidate_url": cr.url,
                "method": method_str,
                "tier": tier,
                "similarity_score": getattr(cr, "similarity_score", None),
                "verified_live": bool(verified),
            }
        )
    return cands


def filter_tier1(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Strict tier-1 filter for the bulk run.

    Allowed:
        - method in TIER1_METHODS and verified_live (the surface tier-1 set)
        - method == "redirect_chain" excluded (#197 — suppressed everywhere)
        - method == "sitemap_search" excluded by default (would need same-token
          check; we hold it out of bulk-run quality envelope)
    """
    if not TIER1_ONLY_MODE:
        return candidates
    return [c for c in candidates if c["method"] in TIER1_METHODS and c["verified_live"]]


def compute_confidence(candidate: dict[str, Any]) -> float:
    """Final confidence score for a candidate.

    Combines:
      - method strength (some methods are more reliable than others)
      - similarity score (if present)
      - verified-live boost
    Output clipped to [0.0, 1.0].
    """
    method_floor = {
        "url_mutation": 0.85,
        "strip_index": 0.85,
        "wikipedia_suggest": 0.90,
        "github_api_redirect": 0.95,
    }.get(candidate["method"], 0.5)
    sim = candidate.get("similarity_score") or 0.0
    verified_boost = 0.05 if candidate["verified_live"] else -0.15
    score = method_floor + 0.10 * (sim if sim > 0 else 0) + verified_boost
    return max(0.0, min(1.0, score))
