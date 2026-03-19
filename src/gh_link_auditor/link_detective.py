"""Dead link investigation orchestrator (Cheery Littlebottom).

Coordinates redirect detection, archive lookups, URL heuristics,
and GitHub API queries to produce forensic reports with candidate
replacement URLs ranked by confidence.

See LLD #20 §2.5 for investigation pipeline logic.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from urllib.parse import urlparse

from gh_link_auditor.archive_client import ArchiveClient
from gh_link_auditor.false_positives import PARKING_DOMAINS
from gh_link_auditor.github_resolver import GitHubResolver
from gh_link_auditor.redirect_resolver import RedirectResolver, SSRFBlocked
from gh_link_auditor.similarity import compute_similarity
from gh_link_auditor.sitemap_searcher import fetch_sitemap, search_sitemap_for_match
from gh_link_auditor.url_heuristic import URLHeuristic
from src.logging_config import setup_logging

logger = setup_logging("link_detective")


# ---------------------------------------------------------------------------
# Data structures (LLD §2.3)
# ---------------------------------------------------------------------------


class InvestigationMethod(Enum):
    """How a candidate replacement URL was discovered."""

    REDIRECT_CHAIN = "redirect_chain"
    URL_MUTATION = "url_mutation"
    URL_HEURISTIC = "url_heuristic"
    SITEMAP_SEARCH = "sitemap_search"
    GITHUB_API_REDIRECT = "github_api_redirect"
    ARCHIVE_ONLY = "archive_only"


@dataclass
class CandidateReplacement:
    """A candidate replacement URL with discovery metadata."""

    url: str
    method: InvestigationMethod
    similarity_score: float
    verified_live: bool


@dataclass
class Investigation:
    """Results of investigating a dead link."""

    archive_snapshot: str | None
    archive_title: str | None
    archive_content_summary: str | None
    candidate_replacements: list[CandidateReplacement] = field(default_factory=list)
    investigation_log: list[str] = field(default_factory=list)


@dataclass
class ForensicReport:
    """Complete forensic report for a dead URL."""

    dead_url: str
    http_status: int | str
    investigation: Investigation


# ---------------------------------------------------------------------------
# Internal helper (mock target for testing)
# ---------------------------------------------------------------------------


def _fetch_page_content(url: str) -> str | None:
    """Fetch page content for similarity comparison.

    Args:
        url: URL to fetch.

    Returns:
        Page text content, or None on failure.
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "gh-link-auditor/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            return resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError):
        return None


# ---------------------------------------------------------------------------
# LinkDetective orchestrator
# ---------------------------------------------------------------------------


class LinkDetective:
    """Orchestrate dead link investigation pipeline."""

    def __init__(self, state_db=None) -> None:
        """Initialize with optional state database for caching.

        Args:
            state_db: StateDatabase instance for caching results.
        """
        self._state_db = state_db
        self._redirect_resolver = RedirectResolver()
        self._archive_client = ArchiveClient()
        self._url_heuristic = URLHeuristic()
        self._github_resolver = GitHubResolver()

    def investigate(self, dead_url: str, http_status: int | str) -> ForensicReport:
        """Orchestrate investigation pipeline and return forensic report.

        Pipeline stages (LLD §2.5):
        1. Validate URL scheme
        2. Check cache
        3. Redirect detection (short-circuit on high confidence)
        4. URL mutations
        5. Archive lookup
        6. URL pattern heuristics
        7. GitHub-specific resolution
        8. Archive-only fallback
        9. Sort candidates, build report, cache

        Args:
            dead_url: The dead URL to investigate.
            http_status: HTTP status code or error type.

        Returns:
            ForensicReport with investigation results.

        Raises:
            ValueError: If URL scheme is not http or https.
        """
        # 1. Validate URL scheme
        parsed = urlparse(dead_url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Invalid URL scheme: {parsed.scheme!r}. Only http/https supported.")

        # 2. Check cache
        cached = self._check_cache(dead_url)
        if cached is not None:
            return cached

        # 3. Initialize
        candidates: list[CandidateReplacement] = []
        log: list[str] = []
        archive_snapshot: str | None = None
        archive_title: str | None = None
        archive_summary: str | None = None

        # 4. REDIRECT DETECTION (highest priority)
        try:
            final_url, chain_log = self._redirect_resolver.follow_redirects(dead_url)
            log.extend(chain_log)

            if final_url and self._redirect_resolver.verify_live(final_url):
                # Check if redirect landed on a parking/marketplace domain
                final_host = (urlparse(final_url).hostname or "").lower()
                is_parked = any(final_host == d or final_host.endswith(f".{d}") for d in PARKING_DOMAINS)
                if is_parked:
                    log.append(f"Redirect landed on parking domain: {final_url}")
                else:
                    candidate = CandidateReplacement(
                        url=final_url,
                        method=InvestigationMethod.REDIRECT_CHAIN,
                        similarity_score=0.98,
                        verified_live=True,
                    )
                    candidates.append(candidate)

                # Short-circuit on high-confidence redirect (only if not parked)
                if not is_parked and candidates and candidates[-1].similarity_score >= 0.95:
                    report = ForensicReport(
                        dead_url=dead_url,
                        http_status=http_status,
                        investigation=Investigation(
                            archive_snapshot=None,
                            archive_title=None,
                            archive_content_summary=None,
                            candidate_replacements=candidates,
                            investigation_log=log,
                        ),
                    )
                    self._cache_result(report)
                    return report
        except SSRFBlocked as e:
            log.append(f"SSRF blocked: {e}")

        # 5. URL MUTATIONS (excluding trivial www/slash changes)
        _trivial_mutations = {"add_www", "remove_www", "add_trailing_slash", "remove_trailing_slash"}
        try:
            mutations = self._redirect_resolver.test_url_mutations(dead_url)
            for live_url, mutation_type in mutations:
                if mutation_type in _trivial_mutations:
                    log.append(f"URL mutation skipped (trivial): {mutation_type} -> {live_url}")
                    continue
                candidates.append(
                    CandidateReplacement(
                        url=live_url,
                        method=InvestigationMethod.URL_MUTATION,
                        similarity_score=0.90,
                        verified_live=True,
                    )
                )
                log.append(f"URL mutation found: {mutation_type} -> {live_url}")
        except Exception as e:
            log.append(f"URL mutation check failed: {e}")

        # 6. ARCHIVE LOOKUP
        try:
            snapshot = self._archive_client.get_latest_snapshot(dead_url)
            if snapshot:
                snapshot_url = f"https://web.archive.org/web/{snapshot['timestamp']}/{snapshot['url']}"
                archive_snapshot = snapshot_url
                html = self._archive_client.fetch_snapshot_content(snapshot_url)
                if html:
                    archive_title = self._archive_client.extract_title(html)
                    archive_summary = self._archive_client.extract_content_summary(html)
                log.append(f"Archive found: {snapshot['timestamp']}")
            else:
                log.append("No archive snapshot found")
        except Exception as e:
            log.append(f"Archive lookup failed: {e}")

        # 7. SITEMAP SEARCH (same-site page discovery)
        domain = parsed.hostname or ""
        if domain and archive_title:
            try:
                sitemap_urls = fetch_sitemap(domain)
                if sitemap_urls:
                    log.append(f"Sitemap found: {len(sitemap_urls)} URLs")
                    matches = search_sitemap_for_match(sitemap_urls, parsed.path, archive_title)
                    for match_url in matches:
                        if self._redirect_resolver.verify_live(match_url):
                            if archive_summary:
                                page_content = _fetch_page_content(match_url)
                                if page_content:
                                    score = compute_similarity(archive_summary, page_content)
                                else:
                                    score = 0.5
                            else:
                                score = 0.5

                            candidates.append(
                                CandidateReplacement(
                                    url=match_url,
                                    method=InvestigationMethod.SITEMAP_SEARCH,
                                    similarity_score=score,
                                    verified_live=True,
                                )
                            )
                            log.append(f"Sitemap match: {match_url} (score={score:.2f})")
                else:
                    log.append("No sitemap found")
            except Exception as e:
                log.append(f"Sitemap search failed: {e}")

        # 8. URL PATTERN HEURISTICS (requires archive title)
        if archive_title:
            try:
                original_path = parsed.path
                candidate_urls = self._url_heuristic.generate_candidates(domain, archive_title, original_path)
                live_urls = self._url_heuristic.probe_candidates(candidate_urls, max_results=3)

                for url in live_urls:
                    if archive_summary:
                        page_content = _fetch_page_content(url)
                        if page_content:
                            score = compute_similarity(archive_summary, page_content)
                        else:
                            score = 0.3
                    else:
                        score = 0.3

                    if score >= 0.5:
                        candidates.append(
                            CandidateReplacement(
                                url=url,
                                method=InvestigationMethod.URL_HEURISTIC,
                                similarity_score=score,
                                verified_live=True,
                            )
                        )
                        log.append(f"Heuristic candidate: {url} (score={score:.2f})")
            except Exception as e:
                log.append(f"URL heuristic check failed: {e}")

        # 9. GITHUB-SPECIFIC RESOLUTION
        if self._github_resolver.is_github_url(dead_url):
            try:
                owner, repo, file_path = self._github_resolver._parse_github_url(dead_url)
                new_repo_url = self._github_resolver.resolve_repo_redirect(owner, repo)
                if new_repo_url:
                    new_file_url = self._github_resolver.reconstruct_file_url(dead_url, new_repo_url)
                    if self._redirect_resolver.verify_live(new_file_url):
                        candidates.append(
                            CandidateReplacement(
                                url=new_file_url,
                                method=InvestigationMethod.GITHUB_API_REDIRECT,
                                similarity_score=1.0,
                                verified_live=True,
                            )
                        )
                        log.append(f"GitHub redirect: {dead_url} -> {new_file_url}")
            except Exception as e:
                log.append(f"GitHub resolution failed: {e}")

        # 10. Archive-only fallback
        if archive_snapshot and not any(c.verified_live for c in candidates):
            candidates.append(
                CandidateReplacement(
                    url=archive_snapshot,
                    method=InvestigationMethod.ARCHIVE_ONLY,
                    similarity_score=0.0,
                    verified_live=False,
                )
            )
            log.append(f"Archive-only fallback: {archive_snapshot}")

        # 11. Sort candidates by similarity_score descending
        candidates.sort(key=lambda c: c.similarity_score, reverse=True)

        # 12. Build report
        report = ForensicReport(
            dead_url=dead_url,
            http_status=http_status,
            investigation=Investigation(
                archive_snapshot=archive_snapshot,
                archive_title=archive_title,
                archive_content_summary=archive_summary,
                candidate_replacements=candidates,
                investigation_log=log,
            ),
        )

        # 13. Cache result
        self._cache_result(report)

        return report

    def _check_cache(self, dead_url: str) -> ForensicReport | None:
        """Return cached report if URL was previously investigated.

        Args:
            dead_url: URL to look up in cache.

        Returns:
            Cached ForensicReport, or None if not cached.
        """
        # Cache integration with state_db is a future enhancement
        return None

    def _cache_result(self, report: ForensicReport) -> None:
        """Store investigation result in state database.

        Args:
            report: ForensicReport to cache.
        """
        # Cache integration with state_db is a future enhancement
        pass
