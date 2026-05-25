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


def _is_redirect_to_renamed_location(dead_url: str, final_url: str | None) -> bool:
    """True when ``final_url`` is a meaningfully different location from
    ``dead_url`` — indicating the dead URL only "works" via redirect to a
    renamed canonical address.

    Currently handles:
    - github.com URLs where owner or repo path segments differ
    - any URL where the host differs entirely

    Stays conservative: same-host docs-reorganization redirects don't count
    here (too many false positives — many sites silently redirect everything,
    e.g. http -> https or www-prefix normalization that doesn't represent a
    real rename).
    """
    if not final_url or final_url == dead_url:
        return False

    from urllib.parse import urlparse

    d = urlparse(dead_url)
    f = urlparse(final_url)

    # Different host: counts as a rename (org or domain moved)
    if d.netloc.lower() != f.netloc.lower():
        return True

    # Same host. For github.com URLs, look for an owner/repo rename
    if d.netloc.lower() == "github.com":
        d_parts = d.path.strip("/").split("/")
        f_parts = f.path.strip("/").split("/")
        if len(d_parts) >= 2 and len(f_parts) >= 2:
            if d_parts[0] != f_parts[0] or d_parts[1] != f_parts[1]:
                return True

    return False


def gate_dead_url_still_dead(
    repo_full_name: str,
    candidate: dict[str, Any],
    db: Any,
    *,
    http_check: HttpCheck | None = None,
) -> GateResult:
    """Fail when the dead URL serves direct 2xx content (it's been resurrected).

    PASS in two situations:
    1. dead URL is still non-2xx (the original "dead" condition)
    2. dead URL returns 2xx but only via a redirect to a renamed canonical
       location (different host, or different github.com owner/repo) —
       in that case the PR to update to the canonical target is a real fix
       (the redirect is fragile; the new URL is the durable address)
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
    final_url = result.get("final_url")

    if status_code is not None and 200 <= status_code < 300:
        if _is_redirect_to_renamed_location(dead_url, final_url):
            return GateResult(
                name="dead_url_still_dead",
                passed=True,
                reason=(
                    f"dead URL returned {status_code} via redirect to renamed location; PR updates to canonical target"
                ),
                evidence={
                    "dead_url": dead_url,
                    "status_code": status_code,
                    "final_url": final_url,
                    "redirect_to_renamed": True,
                },
            )
        return GateResult(
            name="dead_url_still_dead",
            passed=False,
            reason=f"dead URL returned {status_code}; it has been resurrected (serves direct content)",
            evidence={
                "dead_url": dead_url,
                "status_code": status_code,
                "final_url": final_url,
                "redirect_to_renamed": False,
            },
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
                    encoding="utf-8",
                    errors="replace",
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
# Hard gate #1 (#288): anti-AI text scan in repo + maintainer profile
# ---------------------------------------------------------------------------


_AI_SCAN_FILES = (
    "README.md",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "SECURITY.md",
    ".github/CONTRIBUTING.md",
    ".github/PULL_REQUEST_TEMPLATE.md",
)


def gate_anti_ai(
    repo_full_name: str,
    candidate: dict[str, Any],
    db: Any,
    *,
    subagent: Any = None,
    content_fetch: ContentFetch | None = None,
    prompt_path: Any = None,
) -> GateResult:
    """Subagent-classified anti-AI policy scan (#288).

    Reads the repo's public-facing policy files via the clone-last
    ``GitHubContentsClient``. Concatenates everything that exists and
    sends it to the subagent (``claude --print``) with the
    ``ai_scan.txt`` prompt. Verdict mapping:

    - ``hostile`` → gate FAILS (drop candidate)
    - ``uncertain`` → returns ``passed=False`` with ``reason='needs_operator_review'``
      so ``run_preflight`` can surface NEEDS_OPERATOR_REVIEW
    - ``clean`` → PASS

    When the subagent isn't available (no claude CLI), falls back to
    ``hostile_classifier.ANTI_AI_PHRASES`` keyword pre-scan; any hit →
    ``uncertain``, no hits → ``clean``.
    """
    from gh_link_auditor.preflight.subagent import (
        RealSubagent,
        SubagentVerdict,
        anti_ai_keyword_fallback,
    )

    sub = subagent if subagent is not None else RealSubagent()

    if content_fetch is None:
        from gh_link_auditor.github_api import GitHubContentsClient

        client = GitHubContentsClient()
        owner, _, name = repo_full_name.partition("/")

        def content_fetch(r: str, p: str) -> str | None:
            try:
                return client.fetch_file_content(owner, name, p)
            except Exception:  # noqa: BLE001 — defensive; downstream prefers no-content
                return None

    texts = {}
    for path in _AI_SCAN_FILES:
        content = content_fetch(repo_full_name, path)
        if content:
            texts[path] = content[:4000]  # cap per file to keep prompt manageable

    if not texts:
        # Nothing to scan — defensively PASS rather than fail (the repo has
        # no policy docs to forbid AI; this is the common case).
        return GateResult(
            name="anti_ai",
            passed=True,
            reason="no policy files found to scan",
            evidence={"files_scanned": 0},
        )

    # Subagent path
    if sub is not None and hasattr(sub, "run") and getattr(sub, "is_available", lambda: True)():
        if prompt_path is None:
            from pathlib import Path

            prompt_path = Path(__file__).resolve().parent.parent.parent.parent / "prompts" / "preflight" / "ai_scan.txt"
        try:
            verdict = sub.run(prompt_path, {"repo": repo_full_name, "texts": texts})
        except Exception as exc:  # noqa: BLE001 — fall through to fallback
            verdict = None
            evidence_extra = {"subagent_error": str(exc)}
        else:
            evidence_extra = {}
        if verdict == SubagentVerdict.HOSTILE:
            return GateResult(
                name="anti_ai",
                passed=False,
                reason="subagent classified content as hostile to AI PRs",
                evidence={"files_scanned": len(texts), **evidence_extra},
            )
        if verdict == SubagentVerdict.CLEAN:
            return GateResult(
                name="anti_ai",
                passed=True,
                reason="subagent classified content as clean",
                evidence={"files_scanned": len(texts), **evidence_extra},
            )
        if verdict == SubagentVerdict.UNCERTAIN:
            return GateResult(
                name="anti_ai",
                passed=False,
                reason="needs_operator_review",
                evidence={"files_scanned": len(texts), "subagent_verdict": "uncertain", **evidence_extra},
            )
        # subagent error / unknown verdict → fall through to keyword fallback

    # Fallback: keyword scan
    combined = "\n\n".join(texts.values())
    fallback_verdict = anti_ai_keyword_fallback(combined)
    if fallback_verdict == SubagentVerdict.UNCERTAIN:
        return GateResult(
            name="anti_ai",
            passed=False,
            reason="needs_operator_review",
            evidence={"files_scanned": len(texts), "fallback": "keyword_hit"},
        )
    return GateResult(
        name="anti_ai",
        passed=True,
        reason="keyword fallback found no anti-AI phrases",
        evidence={"files_scanned": len(texts), "fallback": "keyword_clean"},
    )


# ---------------------------------------------------------------------------
# Hard gate #3 (#290): blacklist (repo + maintainer)
# ---------------------------------------------------------------------------


def gate_blacklist(
    repo_full_name: str,
    candidate: dict[str, Any],
    db: Any,
) -> GateResult:
    """Fail when the repo OR its maintainer is in the unified-DB blacklist.

    The maintainer-level plumbing already exists in
    ``unified_db.is_blacklisted(repo_url, maintainer=None)`` (#208 was
    correct about the column being unused at most call sites; this gate
    is one of the first callers to pass it).
    """
    if db is None or not hasattr(db, "is_blacklisted"):
        return GateResult(
            name="blacklist",
            passed=True,
            reason="no db available; cannot check blacklist (defensive PASS)",
            evidence={},
        )

    repo_url = f"https://github.com/{repo_full_name}"
    maintainer = repo_full_name.partition("/")[0]
    if db.is_blacklisted(repo_url, maintainer):
        return GateResult(
            name="blacklist",
            passed=False,
            reason="repo or maintainer is blacklisted",
            evidence={"repo_url": repo_url, "maintainer": maintainer},
        )
    return GateResult(
        name="blacklist",
        passed=True,
        reason="not blacklisted",
        evidence={"repo_url": repo_url, "maintainer": maintainer},
    )


# ---------------------------------------------------------------------------
# Hard gate #7 (#294): candidate URL redirects to unrelated content
# ---------------------------------------------------------------------------


def gate_redirect_target_related(
    repo_full_name: str,
    candidate: dict[str, Any],
    db: Any,
    *,
    subagent: Any = None,
    http_check: HttpCheck | None = None,
    landing_fetch: Callable[[str], dict[str, str]] | None = None,
    prompt_path: Any = None,
) -> GateResult:
    """Subagent-classified semantic check on redirect landing pages (#294).

    Per operator: pure URL redirects that land on the right page are FINE.
    Only fail if the final landing page is unrelated to the candidate's
    expected content.

    No-redirect case (`final_url == candidate_url`) skips the subagent
    and passes immediately. Subagent verdict ``unrelated`` → FAIL;
    ``clean`` → PASS. Anything else (including subagent unavailable)
    defensively passes — we don't want to drop perfectly good candidates
    just because we can't reach the subagent.
    """
    from gh_link_auditor.preflight.subagent import RealSubagent, SubagentVerdict

    candidate_url = candidate.get("candidate_url") or ""
    if not candidate_url:
        return GateResult(
            name="redirect_target_related",
            passed=True,
            reason="no candidate_url to check (defensive PASS)",
            evidence={},
        )

    check = http_check or _default_http_check
    result = check(candidate_url)
    final_url = result.get("final_url") or candidate_url
    if final_url == candidate_url:
        return GateResult(
            name="redirect_target_related",
            passed=True,
            reason="no redirect",
            evidence={"candidate_url": candidate_url, "final_url": final_url},
        )

    if landing_fetch is None:
        # Minimal default: use urllib to GET the landing page and extract
        # title-ish snippet. Kept tiny to avoid pulling in BeautifulSoup.
        def landing_fetch(url: str) -> dict[str, str]:
            try:
                import urllib.request

                req = urllib.request.Request(url, headers={"User-Agent": "gh-link-auditor/preflight"})
                with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 — http handled
                    body = resp.read(8192).decode("utf-8", errors="replace")
                return {"title": "", "h1": "", "body_snippet": body[:200]}
            except Exception:  # noqa: BLE001
                return {"title": "", "h1": "", "body_snippet": ""}

    landing = landing_fetch(final_url)

    sub = subagent if subagent is not None else RealSubagent()
    if sub is not None and hasattr(sub, "run") and getattr(sub, "is_available", lambda: True)():
        if prompt_path is None:
            from pathlib import Path

            prompt_path = (
                Path(__file__).resolve().parent.parent.parent.parent / "prompts" / "preflight" / "redirect_target.txt"
            )
        try:
            verdict = sub.run(
                prompt_path,
                {
                    "candidate_url": candidate_url,
                    "final_url": final_url,
                    "expected_topic": candidate.get("source_file") or "",
                    "landing_page": landing,
                },
            )
        except Exception as exc:  # noqa: BLE001
            return GateResult(
                name="redirect_target_related",
                passed=True,
                reason=f"subagent error; defensive PASS ({exc})",
                evidence={"candidate_url": candidate_url, "final_url": final_url},
            )
        if verdict == SubagentVerdict.UNRELATED:
            return GateResult(
                name="redirect_target_related",
                passed=False,
                reason="subagent: redirect landing page is unrelated",
                evidence={"candidate_url": candidate_url, "final_url": final_url, "landing": landing},
            )
        if verdict == SubagentVerdict.CLEAN:
            return GateResult(
                name="redirect_target_related",
                passed=True,
                reason="subagent: redirect lands on related content",
                evidence={"candidate_url": candidate_url, "final_url": final_url},
            )
        # uncertain / unexpected → defensive pass (operator can review if needed)
        return GateResult(
            name="redirect_target_related",
            passed=True,
            reason=f"subagent verdict {verdict}; defensive PASS",
            evidence={"candidate_url": candidate_url, "final_url": final_url},
        )

    # No subagent → defensive pass (we don't have a non-LLM signal here)
    return GateResult(
        name="redirect_target_related",
        passed=True,
        reason="subagent unavailable; defensive PASS",
        evidence={"candidate_url": candidate_url, "final_url": final_url},
    )


# ---------------------------------------------------------------------------
# Registry: full 10-gate set after PR-ε (#288, #290, #294 appended).
# ---------------------------------------------------------------------------


HARD_GATES: list[Callable[..., GateResult]] = [
    gate_anti_ai,
    gate_repo_active,
    gate_blacklist,
    gate_dead_url_still_present,
    gate_dead_url_still_dead,
    gate_candidate_url_alive,
    gate_redirect_target_related,
    gate_no_duplicate_pr,
    gate_no_markdown_corruption,
    gate_stars_floor,
]
