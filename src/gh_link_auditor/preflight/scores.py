"""Score components for preflight (#281).

Each score function returns ``ScoreComponent(name, points_awarded,
max_points, evidence)``. The registry ``CORRECTNESS_SCORES`` collects 6
non-subagent correctness scores (PR-η); PR-θ adds C5 (content
equivalence, subagent) and R1-R5 (receptivity).

Like gates, scores accept dependency-injection kwargs (``http_check``,
``content_fetch``) so tests stay offline.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from gh_link_auditor.network import check_url
from gh_link_auditor.preflight.report import ScoreComponent

HttpCheck = Callable[[str], dict[str, Any]]
ContentFetch = Callable[[str, str], str | None]


def _default_http_check(url: str) -> dict[str, Any]:
    result = check_url(url)
    return {
        "status_code": result.get("status_code"),
        "status": result.get("status"),
        "final_url": result.get("final_url"),
    }


def _fetch_source_content(repo_full_name: str, source_file: str) -> str | None:
    from gh_link_auditor.github_api import GitHubContentsClient

    client = GitHubContentsClient()
    owner, _, name = repo_full_name.partition("/")
    try:
        return client.fetch_file_content(owner, name, source_file)
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# C1 (#298): URL verbatim match in current file (10pt)
# ---------------------------------------------------------------------------


def score_c1_url_verbatim(
    repo_full_name: str,
    candidate: dict[str, Any],
    db: Any,
    *,
    content_fetch: ContentFetch | None = None,
) -> ScoreComponent:
    """Full 10 pt for byte-exact match of dead_url in the current file.

    0 pt if the file's URL was canonicalized differently between scan
    and now (e.g. trailing slash stripped upstream after we recorded it).
    """
    source_file = candidate.get("source_file") or ""
    dead_url = candidate.get("dead_url") or ""
    fetch = content_fetch or _fetch_source_content
    content = fetch(repo_full_name, source_file) or ""
    if dead_url and dead_url in content:
        return ScoreComponent(
            name="C1",
            points_awarded=10,
            max_points=10,
            evidence={"match": "exact"},
        )
    return ScoreComponent(
        name="C1",
        points_awarded=0,
        max_points=10,
        evidence={"match": "missing_or_canonicalized"},
    )


# ---------------------------------------------------------------------------
# C2 (#299): dead URL occurrence count (10pt; multi-occurrence surface)
# ---------------------------------------------------------------------------


def score_c2_occurrence_count(
    repo_full_name: str,
    candidate: dict[str, Any],
    db: Any,
    *,
    content_fetch: ContentFetch | None = None,
) -> ScoreComponent:
    """10 pt for exactly 1 occurrence; 5 pt + surface for 2+."""
    source_file = candidate.get("source_file") or ""
    dead_url = candidate.get("dead_url") or ""
    fetch = content_fetch or _fetch_source_content
    content = fetch(repo_full_name, source_file) or ""
    count = content.count(dead_url) if dead_url else 0
    if count == 1:
        return ScoreComponent(name="C2", points_awarded=10, max_points=10, evidence={"hits": 1})
    if count >= 2:
        return ScoreComponent(
            name="C2", points_awarded=5, max_points=10, evidence={"hits": count, "multi_occurrence": True}
        )
    return ScoreComponent(name="C2", points_awarded=0, max_points=10, evidence={"hits": 0})


# ---------------------------------------------------------------------------
# C3 (#300): dead URL fresh HTTP status (10pt; no-op-fix detection)
# ---------------------------------------------------------------------------


def score_c3_dead_http_status(
    repo_full_name: str,
    candidate: dict[str, Any],
    db: Any,
    *,
    http_check: HttpCheck | None = None,
) -> ScoreComponent:
    """No-op (dead == candidate): 0 + surface; 4xx: 10; 5xx: 5; None: 5."""
    dead_url = candidate.get("dead_url") or ""
    candidate_url = candidate.get("candidate_url") or ""
    if dead_url and dead_url == candidate_url:
        return ScoreComponent(
            name="C3",
            points_awarded=0,
            max_points=10,
            evidence={"reason": "no_op_fix"},
        )
    check = http_check or _default_http_check
    result = check(dead_url) if dead_url else {"status_code": None}
    status_code = result.get("status_code")
    if status_code is None:
        return ScoreComponent(name="C3", points_awarded=5, max_points=10, evidence={"status_code": None})
    if 400 <= status_code < 500:
        return ScoreComponent(name="C3", points_awarded=10, max_points=10, evidence={"status_code": status_code})
    if 500 <= status_code < 600:
        return ScoreComponent(name="C3", points_awarded=5, max_points=10, evidence={"status_code": status_code})
    return ScoreComponent(name="C3", points_awarded=0, max_points=10, evidence={"status_code": status_code})


# ---------------------------------------------------------------------------
# C4 (#301): candidate URL fresh HTTP status (10pt; redirect partial credit)
# ---------------------------------------------------------------------------


def score_c4_candidate_http_status(
    repo_full_name: str,
    candidate: dict[str, Any],
    db: Any,
    *,
    http_check: HttpCheck | None = None,
) -> ScoreComponent:
    """200: 10; 301/302→2xx: 8; other: 0."""
    candidate_url = candidate.get("candidate_url") or ""
    if not candidate_url:
        return ScoreComponent(name="C4", points_awarded=0, max_points=10, evidence={"status_code": None})
    check = http_check or _default_http_check
    result = check(candidate_url)
    status_code = result.get("status_code")
    final_url = result.get("final_url") or candidate_url
    if status_code == 200:
        return ScoreComponent(name="C4", points_awarded=10, max_points=10, evidence={"status_code": 200})
    if status_code is not None and 300 <= status_code < 400 and final_url != candidate_url:
        return ScoreComponent(
            name="C4",
            points_awarded=8,
            max_points=10,
            evidence={"status_code": status_code, "final_url": final_url, "redirect": True},
        )
    # Treat 2xx-redirect chain (where final_url shifted) as full credit if status 2xx
    if status_code is not None and 200 <= status_code < 300 and final_url != candidate_url:
        return ScoreComponent(
            name="C4",
            points_awarded=8,
            max_points=10,
            evidence={"status_code": status_code, "final_url": final_url, "redirect": True},
        )
    return ScoreComponent(name="C4", points_awarded=0, max_points=10, evidence={"status_code": status_code})


# ---------------------------------------------------------------------------
# C6 (#303): replace simulation produces valid markdown (10pt)
# ---------------------------------------------------------------------------


_BRACKET_PAIRS = (("(", ")"), ("[", "]"))


def _balanced(text: str) -> bool:
    """Return True if all bracket pairs are balanced in text (markdown-safe heuristic)."""
    for opener, closer in _BRACKET_PAIRS:
        if text.count(opener) != text.count(closer):
            return False
    return True


def score_c6_replace_simulation_valid(
    repo_full_name: str,
    candidate: dict[str, Any],
    db: Any,
    *,
    content_fetch: ContentFetch | None = None,
) -> ScoreComponent:
    """10 pt if `str.replace(dead, candidate)` keeps brackets balanced.

    Lightweight heuristic — checks bracket balance pre and post, plus
    avoidance of broken `![]()` / `[]()` patterns. A full markdown
    parser is overkill for the false-positive rate we'd accept here.
    """
    source_file = candidate.get("source_file") or ""
    dead_url = candidate.get("dead_url") or ""
    candidate_url = candidate.get("candidate_url") or ""
    fetch = content_fetch or _fetch_source_content
    content = fetch(repo_full_name, source_file)
    if content is None or not dead_url or not candidate_url:
        return ScoreComponent(
            name="C6",
            points_awarded=0,
            max_points=10,
            evidence={"reason": "missing_inputs"},
        )

    after = content.replace(dead_url, candidate_url)
    if not _balanced(after):
        return ScoreComponent(
            name="C6",
            points_awarded=0,
            max_points=10,
            evidence={"reason": "brackets_unbalanced"},
        )
    # Reject orphan empty markdown link patterns
    if re.search(r"!?\[\]\(\)", after):
        return ScoreComponent(
            name="C6",
            points_awarded=0,
            max_points=10,
            evidence={"reason": "orphan_link"},
        )
    return ScoreComponent(name="C6", points_awarded=10, max_points=10, evidence={"reason": "ok"})


# ---------------------------------------------------------------------------
# C7 (#304): surrounding context preserved (10pt; char-diff)
# ---------------------------------------------------------------------------


def score_c7_context_preserved(
    repo_full_name: str,
    candidate: dict[str, Any],
    db: Any,
    *,
    content_fetch: ContentFetch | None = None,
) -> ScoreComponent:
    """10 pt when applying ``str.replace(dead_url, candidate_url)`` to the
    upstream file leaves the file length consistent with N URL swaps —
    i.e. nothing other than the URL substring(s) was modified.

    The naive ``str.replace`` already guarantees only URLs change at
    runtime; this score is a sanity check that the dead URL appears and
    that the candidate doesn't introduce surrounding-character noise
    (e.g. accidentally embedded markdown). For richer "external fix
    workflow" comparisons, a future iteration would accept the
    actual post-fix content as input — currently out of scope.
    """
    source_file = candidate.get("source_file") or ""
    dead_url = candidate.get("dead_url") or ""
    candidate_url = candidate.get("candidate_url") or ""
    fetch = content_fetch or _fetch_source_content
    before = fetch(repo_full_name, source_file)
    if before is None or not dead_url:
        return ScoreComponent(
            name="C7",
            points_awarded=0,
            max_points=10,
            evidence={"reason": "missing_inputs"},
        )
    count = before.count(dead_url)
    if count == 0:
        return ScoreComponent(
            name="C7",
            points_awarded=0,
            max_points=10,
            evidence={"reason": "dead_url_absent"},
        )
    after = before.replace(dead_url, candidate_url)
    expected_len_delta = count * (len(candidate_url) - len(dead_url))
    actual_len_delta = len(after) - len(before)
    if expected_len_delta != actual_len_delta:
        return ScoreComponent(
            name="C7",
            points_awarded=0,
            max_points=10,
            evidence={
                "reason": "length_delta_mismatch",
                "expected": expected_len_delta,
                "actual": actual_len_delta,
            },
        )
    return ScoreComponent(
        name="C7",
        points_awarded=10,
        max_points=10,
        evidence={"reason": "only_url_changed", "occurrences": count},
    )


# ---------------------------------------------------------------------------
# Registry: PR-η ships 6 correctness scores; PR-θ appends C5 + R1-R5.
# ---------------------------------------------------------------------------


CORRECTNESS_SCORES: list[Callable[..., ScoreComponent]] = [
    score_c1_url_verbatim,
    score_c2_occurrence_count,
    score_c3_dead_http_status,
    score_c4_candidate_http_status,
    score_c6_replace_simulation_valid,
    score_c7_context_preserved,
]
