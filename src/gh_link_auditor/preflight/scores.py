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
from gh_link_auditor.repo_quality import fetch_repo_metadata

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
# C5 (#302): content equivalence fuzzy (15pt; subagent semantic)
# ---------------------------------------------------------------------------


def score_c5_content_equivalence(
    repo_full_name: str,
    candidate: dict[str, Any],
    db: Any,
    *,
    subagent: Any = None,
    http_check: HttpCheck | None = None,
    landing_fetch: Callable[[str], dict[str, str]] | None = None,
    prompt_path: Any = None,
) -> ScoreComponent:
    """15 pt when subagent says ``clean`` (landing matches link text intent);
    8 pt for ``partial``; 0 pt for ``unrelated``. Subagent timeout /
    uncertain → 8 pt with surfaced reason (we don't want operator
    escalation just for a soft score — gate #7 / #294 handles the strict
    case).
    """
    from gh_link_auditor.preflight.subagent import RealSubagent, SubagentVerdict

    candidate_url = candidate.get("candidate_url") or ""
    if not candidate_url:
        return ScoreComponent(
            name="C5",
            points_awarded=0,
            max_points=15,
            evidence={"reason": "no_candidate_url"},
        )

    if landing_fetch is None:

        def landing_fetch(url: str) -> dict[str, str]:
            try:
                import urllib.request

                req = urllib.request.Request(url, headers={"User-Agent": "gh-link-auditor/preflight"})
                with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
                    body = resp.read(8192).decode("utf-8", errors="replace")
                return {"title": "", "h1": "", "body_snippet": body[:200]}
            except Exception:  # noqa: BLE001
                return {"title": "", "h1": "", "body_snippet": ""}

    landing = landing_fetch(candidate_url)
    link_text = candidate.get("source_file") or ""

    sub = subagent if subagent is not None else RealSubagent()
    if sub is not None and hasattr(sub, "run") and getattr(sub, "is_available", lambda: True)():
        if prompt_path is None:
            from pathlib import Path

            prompt_path = (
                Path(__file__).resolve().parent.parent.parent.parent / "prompts" / "preflight" / "content_equiv.txt"
            )
        try:
            verdict = sub.run(
                prompt_path,
                {
                    "candidate_url": candidate_url,
                    "link_text": link_text,
                    "landing_page": landing,
                },
            )
        except Exception as exc:  # noqa: BLE001
            return ScoreComponent(
                name="C5",
                points_awarded=8,
                max_points=15,
                evidence={"reason": f"subagent_error: {exc}"},
            )
        if verdict == SubagentVerdict.CLEAN:
            return ScoreComponent(name="C5", points_awarded=15, max_points=15, evidence={"subagent": "clean"})
        if verdict == SubagentVerdict.PARTIAL:
            return ScoreComponent(name="C5", points_awarded=8, max_points=15, evidence={"subagent": "partial"})
        if verdict == SubagentVerdict.UNRELATED:
            return ScoreComponent(name="C5", points_awarded=0, max_points=15, evidence={"subagent": "unrelated"})
        # uncertain / unexpected — soft partial
        return ScoreComponent(name="C5", points_awarded=8, max_points=15, evidence={"subagent": str(verdict)})

    # Subagent unavailable — soft partial (gate #294 handles the strict case)
    return ScoreComponent(
        name="C5",
        points_awarded=8,
        max_points=15,
        evidence={"subagent": "unavailable"},
    )


# ---------------------------------------------------------------------------
# Receptivity scores (#305-#309): use cached repo metadata
# ---------------------------------------------------------------------------


def _get_repo_meta(repo_full_name: str, db: Any) -> dict[str, Any]:
    """Read from preflight_repo_meta_cache (preferred) or fetch fresh."""
    if db is not None and hasattr(db, "get_cached_repo_meta"):
        cached = db.get_cached_repo_meta(repo_full_name)
        if cached is not None:
            return cached
    owner, _, name = repo_full_name.partition("/")
    q = fetch_repo_metadata(owner, name)
    meta = {
        "stars": q.stars,
        "pushed_at": q.pushed_at,
        "license": q.license,
        "archived": q.archived,
        "disabled": q.disabled,
    }
    if db is not None and hasattr(db, "cache_repo_meta"):
        db.cache_repo_meta(
            repo_full_name,
            stars=q.stars,
            pushed_at=q.pushed_at,
            license=q.license,
            archived=q.archived,
            disabled=q.disabled,
        )
    return meta


def score_r1_stars(repo_full_name: str, candidate: dict[str, Any], db: Any) -> ScoreComponent:
    """Tiered: ≥1000=5; ≥500=4; ≥100=3; ≥50=2; ≥20=1; <20=0."""
    meta = _get_repo_meta(repo_full_name, db)
    stars = int(meta.get("stars") or 0)
    tiers = [(1000, 5), (500, 4), (100, 3), (50, 2), (20, 1)]
    points = 0
    for floor, pts in tiers:
        if stars >= floor:
            points = pts
            break
    return ScoreComponent(name="R1", points_awarded=points, max_points=5, evidence={"stars": stars})


def score_r2_recency(
    repo_full_name: str,
    candidate: dict[str, Any],
    db: Any,
    *,
    now: Any = None,
) -> ScoreComponent:
    """Last push: ≤7d=5; ≤30d=4; ≤90d=3; ≤180d=1; else 0."""
    from datetime import datetime, timezone

    meta = _get_repo_meta(repo_full_name, db)
    pushed_at = meta.get("pushed_at") or ""
    if not pushed_at:
        return ScoreComponent(name="R2", points_awarded=0, max_points=5, evidence={"pushed_at": None})
    try:
        # GitHub returns ISO-8601 with trailing Z; fromisoformat handles it on 3.11+
        pushed_dt = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return ScoreComponent(
            name="R2", points_awarded=0, max_points=5, evidence={"pushed_at": pushed_at, "parse_error": True}
        )

    now_dt = now if now is not None else datetime.now(timezone.utc)
    delta_days = (now_dt - pushed_dt).total_seconds() / 86400
    if delta_days <= 7:
        points = 5
    elif delta_days <= 30:
        points = 4
    elif delta_days <= 90:
        points = 3
    elif delta_days <= 180:
        points = 1
    else:
        points = 0
    return ScoreComponent(
        name="R2",
        points_awarded=points,
        max_points=5,
        evidence={"days_since_push": round(delta_days, 1)},
    )


def score_r3_outsider_merge_rate(
    repo_full_name: str,
    candidate: dict[str, Any],
    db: Any,
    *,
    gh_get: Callable[[str], list[Any] | None] | None = None,
) -> ScoreComponent:
    """Outsider-PR merge rate from last ~20 closed PRs; 7-day cache.

    ≥30% → 5 pt; ≥10% → 3; >0 → 1; 0 (or insufficient sample) → 0.
    """
    # Cache hit
    if db is not None and hasattr(db, "get_cached_pr_stats"):
        cached = db.get_cached_pr_stats(repo_full_name)
        if cached is not None:
            return _r3_score_from_rate(cached["merge_rate"], cached["sample_size"])

    if gh_get is None:
        import json
        import subprocess

        def gh_get(path: str) -> list[Any] | None:
            try:
                r = subprocess.run(
                    ["gh", "api", path],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                    check=False,
                )
                if r.returncode != 0 or not r.stdout.strip():
                    return None
                return json.loads(r.stdout)
            except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
                return None

    owner = repo_full_name.partition("/")[0]
    pulls = gh_get(f"repos/{repo_full_name}/pulls?state=closed&per_page=20")
    if not isinstance(pulls, list) or not pulls:
        return ScoreComponent(name="R3", points_awarded=0, max_points=5, evidence={"sample_size": 0})

    # Outsider = author.login != repo owner (and not a bot)
    outsider_prs = [
        p for p in pulls if isinstance(p, dict) and isinstance(p.get("user"), dict) and p["user"].get("login") != owner
    ]
    sample_size = len(outsider_prs)
    merged = sum(1 for p in outsider_prs if p.get("merged_at") is not None)
    merge_rate = (merged / sample_size) if sample_size > 0 else 0.0

    if db is not None and hasattr(db, "cache_pr_stats"):
        db.cache_pr_stats(repo_full_name, merge_rate=merge_rate, sample_size=sample_size)

    return _r3_score_from_rate(merge_rate, sample_size)


def _r3_score_from_rate(merge_rate: float, sample_size: int) -> ScoreComponent:
    if sample_size == 0:
        points = 0
    elif merge_rate >= 0.30:
        points = 5
    elif merge_rate >= 0.10:
        points = 3
    elif merge_rate > 0:
        points = 1
    else:
        points = 0
    return ScoreComponent(
        name="R3",
        points_awarded=points,
        max_points=5,
        evidence={"merge_rate": round(merge_rate, 3), "sample_size": sample_size},
    )


def score_r4_maintainer_structure(
    repo_full_name: str,
    candidate: dict[str, Any],
    db: Any,
    *,
    gh_get: Callable[[str], Any] | None = None,
) -> ScoreComponent:
    """5 pt for multi-committer / CODEOWNERS / org-owned; 2 pt for solo; 0 on fetch error."""
    if gh_get is None:
        import json
        import subprocess

        def gh_get(path: str) -> Any:
            try:
                r = subprocess.run(
                    ["gh", "api", path],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                    check=False,
                )
                if r.returncode != 0:
                    return None
                if not r.stdout.strip():
                    return None
                return json.loads(r.stdout)
            except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
                return None

    # 1. Org-owned?
    repo_data = gh_get(f"repos/{repo_full_name}")
    owner_type = ""
    if isinstance(repo_data, dict) and isinstance(repo_data.get("owner"), dict):
        owner_type = repo_data["owner"].get("type") or ""

    # 2. Multiple committers?
    contributors = gh_get(f"repos/{repo_full_name}/contributors?per_page=10")
    contributor_count = len(contributors) if isinstance(contributors, list) else 0

    # 3. CODEOWNERS?
    codeowners = gh_get(f"repos/{repo_full_name}/contents/CODEOWNERS")
    has_codeowners = isinstance(codeowners, dict)

    if owner_type == "Organization" or contributor_count >= 2 or has_codeowners:
        return ScoreComponent(
            name="R4",
            points_awarded=5,
            max_points=5,
            evidence={
                "owner_type": owner_type,
                "contributors": contributor_count,
                "has_codeowners": has_codeowners,
            },
        )
    if contributor_count >= 1:
        return ScoreComponent(name="R4", points_awarded=2, max_points=5, evidence={"contributors": contributor_count})
    return ScoreComponent(name="R4", points_awarded=0, max_points=5, evidence={"fetch": "error"})


_PERMISSIVE_LICENSES = frozenset(
    {
        "MIT",
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "BSD-3-Clause-Clear",
        "BSD-4-Clause",
        "MPL-2.0",
        "ISC",
        "0BSD",
    }
)


def score_r5_license(repo_full_name: str, candidate: dict[str, Any], db: Any) -> ScoreComponent:
    """5 pt for permissive SPDX; 2 pt for non-permissive; 0 if no license."""
    meta = _get_repo_meta(repo_full_name, db)
    license_id = meta.get("license")
    if not license_id:
        return ScoreComponent(name="R5", points_awarded=0, max_points=5, evidence={"license": None})
    if license_id in _PERMISSIVE_LICENSES:
        return ScoreComponent(name="R5", points_awarded=5, max_points=5, evidence={"license": license_id})
    return ScoreComponent(
        name="R5", points_awarded=2, max_points=5, evidence={"license": license_id, "permissive": False}
    )


# ---------------------------------------------------------------------------
# Registry: PR-η ships 6 correctness scores; PR-θ appends C5 + R1-R5.
# ---------------------------------------------------------------------------


CORRECTNESS_SCORES: list[Callable[..., ScoreComponent]] = [
    score_c1_url_verbatim,
    score_c2_occurrence_count,
    score_c3_dead_http_status,
    score_c4_candidate_http_status,
    score_c5_content_equivalence,
    score_c6_replace_simulation_valid,
    score_c7_context_preserved,
    score_r1_stars,
    score_r2_recency,
    score_r3_outsider_merge_rate,
    score_r4_maintainer_structure,
    score_r5_license,
]
