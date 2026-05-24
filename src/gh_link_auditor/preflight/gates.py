"""Hard gates for preflight (#281).

Each gate is a callable returning ``GateResult(name, passed, reason, evidence)``.
Failures drop the candidate before any fork. The registry ``HARD_GATES`` is
a list that ``run_preflight`` iterates; subsequent PRs append more gates
(PR-ε adds anti_ai, blacklist, redirect_target; this PR ships 7 non-
subagent gates).

The gate functions take ``(repo_full_name, candidate, db, *, subagent=None,
http_check=None, gh_get=None, content_fetch=None)``. The non-db / non-
subagent collaborators are injected so tests can use ``tests/fakes/``
patterns without monkey-patching modules.
"""

from __future__ import annotations

from typing import Any, Callable

from gh_link_auditor.network import check_url
from gh_link_auditor.preflight.report import GateResult
from gh_link_auditor.repo_quality import fetch_repo_metadata

# ---------------------------------------------------------------------------
# Collaborator types for dependency injection
# ---------------------------------------------------------------------------

# (url, ttl_hours) -> RequestResult dict-like with keys 'status_code', 'final_url', 'status'
HttpCheck = Callable[[str], dict[str, Any]]

# (api_path) -> JSON dict; used for gh api fetches that aren't covered by network.check_url
GhGet = Callable[[str], dict[str, Any] | list[Any] | None]

# (repo_full_name, file_path) -> str | None ; clone-last upstream file fetch
ContentFetch = Callable[[str, str], str | None]


def _default_http_check(url: str) -> dict[str, Any]:
    result = check_url(url)
    return {
        "status_code": result.get("status_code"),
        "status": result.get("status"),
        "final_url": result.get("final_url"),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_cached_or_fetch_repo_meta(repo_full_name: str, db: Any) -> dict[str, Any]:
    """Return repo metadata from cache or fresh fetch (#285 + #316).

    Uses ``preflight_repo_meta_cache`` to avoid hitting the GitHub API on
    every gate that needs stars / archived / disabled / license.
    """
    cached = None
    if db is not None and hasattr(db, "get_cached_repo_meta"):
        cached = db.get_cached_repo_meta(repo_full_name)
    if cached is not None:
        return cached

    owner, _, name = repo_full_name.partition("/")
    quality = fetch_repo_metadata(owner, name)
    meta = {
        "repo_full_name": repo_full_name,
        "stars": quality.stars,
        "pushed_at": quality.pushed_at,
        "license": quality.license,
        "archived": quality.archived,
        "disabled": quality.disabled,
    }
    if db is not None and hasattr(db, "cache_repo_meta"):
        db.cache_repo_meta(
            repo_full_name,
            stars=quality.stars,
            pushed_at=quality.pushed_at,
            license=quality.license,
            archived=quality.archived,
            disabled=quality.disabled,
        )
    return meta


# ---------------------------------------------------------------------------
# Hard gate #2 (#289): repo archived or disabled
# ---------------------------------------------------------------------------


def gate_repo_active(repo_full_name: str, candidate: dict[str, Any], db: Any) -> GateResult:
    """Fail when the upstream repo is archived or disabled.

    Either flag means a PR submitted there will sit forever — at best
    ignored, at worst signal-noise that erodes the operator's reputation
    with other maintainers.
    """
    meta = _get_cached_or_fetch_repo_meta(repo_full_name, db)
    archived = bool(meta.get("archived"))
    disabled = bool(meta.get("disabled"))
    if archived or disabled:
        return GateResult(
            name="repo_active",
            passed=False,
            reason="repo is archived" if archived else "repo is disabled",
            evidence={"archived": archived, "disabled": disabled},
        )
    return GateResult(
        name="repo_active",
        passed=True,
        reason="repo is active",
        evidence={"archived": False, "disabled": False},
    )


# ---------------------------------------------------------------------------
# Hard gate #4 (#291): dead URL no longer present in current upstream file
# ---------------------------------------------------------------------------


def gate_dead_url_still_present(
    repo_full_name: str,
    candidate: dict[str, Any],
    db: Any,
    *,
    content_fetch: ContentFetch | None = None,
) -> GateResult:
    """Fail when the upstream file no longer contains the dead URL.

    Either someone else's PR landed first, or the maintainer fixed the
    file by hand. Either way: nothing for us to do.
    """
    source_file = candidate.get("source_file") or ""
    dead_url = candidate.get("dead_url") or ""
    if not source_file or not dead_url:
        return GateResult(
            name="dead_url_still_present",
            passed=False,
            reason="missing source_file or dead_url on candidate",
            evidence={"source_file": source_file, "dead_url": dead_url},
        )

    if content_fetch is None:
        # Real fetch path — kept minimal here; tests should inject content_fetch
        from gh_link_auditor.github_api import GitHubContentsClient

        client = GitHubContentsClient()
        owner, _, name = repo_full_name.partition("/")
        content_fetch = lambda r, p: client.fetch_file_content(owner, name, p)  # noqa: E731

    content = content_fetch(repo_full_name, source_file)
    if content is None:
        return GateResult(
            name="dead_url_still_present",
            passed=False,
            reason="upstream file could not be fetched",
            evidence={"source_file": source_file},
        )
    if dead_url not in content:
        return GateResult(
            name="dead_url_still_present",
            passed=False,
            reason="dead URL no longer appears in current upstream file",
            evidence={"source_file": source_file, "dead_url": dead_url},
        )
    return GateResult(
        name="dead_url_still_present",
        passed=True,
        reason="dead URL present",
        evidence={"source_file": source_file},
    )


# ---------------------------------------------------------------------------
# Hard gate #5 (#292): dead URL is now alive (fresh re-verify)
# ---------------------------------------------------------------------------


def gate_dead_url_still_dead(
    repo_full_name: str,
    candidate: dict[str, Any],
    db: Any,
    *,
    http_check: HttpCheck | None = None,
) -> GateResult:
    """Fail when the dead URL returns 2xx — it's been resurrected.

    Filing a PR to "fix" a URL that works now would be a no-op at best,
    embarrassing at worst.
    """
    dead_url = candidate.get("dead_url") or ""
    if not dead_url:
        return GateResult(
            name="dead_url_still_dead",
            passed=False,
            reason="no dead_url on candidate",
            evidence={},
        )

    check = http_check or _default_http_check
    result = check(dead_url)
    status_code = result.get("status_code")
    if status_code is not None and 200 <= status_code < 300:
        return GateResult(
            name="dead_url_still_dead",
            passed=False,
            reason=f"dead URL returned {status_code}; it has been resurrected",
            evidence={"dead_url": dead_url, "status_code": status_code},
        )
    return GateResult(
        name="dead_url_still_dead",
        passed=True,
        reason=f"dead URL still {result.get('status', 'down')}",
        evidence={"dead_url": dead_url, "status_code": status_code},
    )


# ---------------------------------------------------------------------------
# Hard gate #6 (#293): candidate URL not 2xx (fresh re-verify)
# ---------------------------------------------------------------------------


def gate_candidate_url_alive(
    repo_full_name: str,
    candidate: dict[str, Any],
    db: Any,
    *,
    http_check: HttpCheck | None = None,
) -> GateResult:
    """Fail when the candidate URL is itself broken."""
    candidate_url = candidate.get("candidate_url") or ""
    if not candidate_url:
        return GateResult(
            name="candidate_url_alive",
            passed=False,
            reason="no candidate_url on candidate",
            evidence={},
        )

    check = http_check or _default_http_check
    result = check(candidate_url)
    status_code = result.get("status_code")
    if status_code is None or not (200 <= status_code < 400):
        return GateResult(
            name="candidate_url_alive",
            passed=False,
            reason=f"candidate URL returned {status_code}; not alive",
            evidence={"candidate_url": candidate_url, "status_code": status_code},
        )
    return GateResult(
        name="candidate_url_alive",
        passed=True,
        reason=f"candidate URL {status_code}",
        evidence={
            "candidate_url": candidate_url,
            "status_code": status_code,
            "final_url": result.get("final_url"),
        },
    )


# ---------------------------------------------------------------------------
# Hard gate #8 (#295): duplicate PR already open in upstream repo
# ---------------------------------------------------------------------------


def gate_no_duplicate_pr(
    repo_full_name: str,
    candidate: dict[str, Any],
    db: Any,
    *,
    gh_get: GhGet | None = None,
) -> GateResult:
    """Fail when an open PR already references either URL.

    Avoids stacking duplicate PRs on the same upstream review surface —
    maintainer-time is the bottleneck; an in-flight PR by anyone is
    enough to defer ours.
    """
    dead_url = candidate.get("dead_url") or ""
    candidate_url = candidate.get("candidate_url") or ""

    if gh_get is None:
        import json
        import subprocess

        def _gh(api_path: str) -> Any:
            try:
                result = subprocess.run(
                    ["gh", "api", api_path],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                if result.returncode != 0:
                    return None
                return json.loads(result.stdout) if result.stdout.strip() else None
            except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
                return None

        gh_get = _gh

    pulls = gh_get(f"repos/{repo_full_name}/pulls?state=open&per_page=100")
    if not isinstance(pulls, list):
        return GateResult(
            name="no_duplicate_pr",
            passed=True,
            reason="could not enumerate open PRs; assuming no duplicate",
            evidence={"pulls_fetched": False},
        )
    for pr in pulls:
        body = (pr.get("body") or "") if isinstance(pr, dict) else ""
        title = (pr.get("title") or "") if isinstance(pr, dict) else ""
        haystack = f"{title}\n{body}"
        if (dead_url and dead_url in haystack) or (candidate_url and candidate_url in haystack):
            return GateResult(
                name="no_duplicate_pr",
                passed=False,
                reason="existing open PR mentions one of our URLs",
                evidence={"pr_number": pr.get("number"), "pr_url": pr.get("html_url")},
            )
    return GateResult(
        name="no_duplicate_pr",
        passed=True,
        reason=f"no open PR mentions either URL ({len(pulls)} open PRs scanned)",
        evidence={"open_pr_count": len(pulls)},
    )


# ---------------------------------------------------------------------------
# Hard gate #9 (#296): markdown corruption — reuse _is_safely_replaceable
# ---------------------------------------------------------------------------


def gate_no_markdown_corruption(
    repo_full_name: str,
    candidate: dict[str, Any],
    db: Any,
) -> GateResult:
    """Fail when ``str.replace(dead, candidate)`` would corrupt markdown.

    Delegates to ``tools.derive_replacement_prs._is_safely_replaceable``
    — the same check tool A applies in ``safe_rows`` filtering. Including
    it as a hard gate gives us defense-in-depth: if a candidate slips
    through the filter (e.g. via direct ``run_preflight`` call), the
    AndreaVidali-style near-miss still trips here.
    """
    from tools.derive_replacement_prs import _is_safely_replaceable

    dead_url = candidate.get("dead_url") or ""
    candidate_url = candidate.get("candidate_url") or ""
    ok, reason = _is_safely_replaceable(dead_url, candidate_url)
    if not ok:
        return GateResult(
            name="no_markdown_corruption",
            passed=False,
            reason=f"replacement would corrupt markdown ({reason})",
            evidence={"dead_url": dead_url, "candidate_url": candidate_url, "reason": reason},
        )
    return GateResult(
        name="no_markdown_corruption",
        passed=True,
        reason="markdown replacement is safe",
        evidence={"dead_url": dead_url, "candidate_url": candidate_url},
    )


# ---------------------------------------------------------------------------
# Hard gate #10 (#297): stars below operator floor (= 20)
# ---------------------------------------------------------------------------


DEFAULT_STARS_FLOOR = 20


def gate_stars_floor(
    repo_full_name: str,
    candidate: dict[str, Any],
    db: Any,
    *,
    floor: int = DEFAULT_STARS_FLOOR,
) -> GateResult:
    """Fail when the repo has fewer than ``floor`` stars (operator floor = 20).

    Low-star repos are usually personal sandboxes that won't receive
    drive-by PRs gracefully; the cost-benefit doesn't justify the
    submission risk.
    """
    meta = _get_cached_or_fetch_repo_meta(repo_full_name, db)
    stars = int(meta.get("stars") or 0)
    if stars < floor:
        return GateResult(
            name="stars_floor",
            passed=False,
            reason=f"repo has {stars} stars; floor is {floor}",
            evidence={"stars": stars, "floor": floor},
        )
    return GateResult(
        name="stars_floor",
        passed=True,
        reason=f"repo has {stars} stars (floor: {floor})",
        evidence={"stars": stars, "floor": floor},
    )


# ---------------------------------------------------------------------------
# Registry: PR-δ ships 7 non-subagent gates; PR-ε will append 3 more.
# ---------------------------------------------------------------------------


HARD_GATES: list[Callable[..., GateResult]] = [
    gate_repo_active,
    gate_dead_url_still_present,
    gate_dead_url_still_dead,
    gate_candidate_url_alive,
    gate_no_duplicate_pr,
    gate_no_markdown_corruption,
    gate_stars_floor,
]
