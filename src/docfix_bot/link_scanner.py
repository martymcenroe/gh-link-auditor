"""Broken link detection with anti-bot handling.

See LLD #2 §2.4 for link_scanner specification.
Deviation: synchronous (not async) to match codebase conventions.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

import httpx

from docfix_bot.config import get_http_timeout, get_user_agent
from docfix_bot.models import (
    BotConfig,
    BrokenLink,
    ScanResult,
    TargetRepository,
    make_broken_link,
    now_iso,
)
from docfix_bot.url_validator import validate_ip_safety

logger = logging.getLogger(__name__)

_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
_URL_RE = re.compile(r"https?://[^\s)>\]]+")

# Status codes that indicate a broken link
_BROKEN_STATUSES = {404, 410, 521, 522, 523, 525}

# Anti-bot headers for retry
_BROWSER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def extract_links_from_markdown(content: str) -> list[tuple[str, int]]:
    """Extract all HTTP(S) links from markdown content with line numbers.

    Args:
        content: Raw markdown text.

    Returns:
        List of (url, line_number) tuples.
    """
    results: list[tuple[str, int]] = []
    seen: set[str] = set()

    for i, line in enumerate(content.splitlines(), start=1):
        # Extract markdown links
        for match in _MARKDOWN_LINK_RE.finditer(line):
            url = match.group(2).strip()
            if url.startswith("http") and url not in seen:
                seen.add(url)
                results.append((url, i))

        # Extract bare URLs not in markdown links
        for match in _URL_RE.finditer(line):
            url = match.group(0).strip()
            if url not in seen:
                seen.add(url)
                results.append((url, i))

    return results


def check_link(
    url: str,
    config: BotConfig,
    max_retries: int = 3,
) -> tuple[int, str | None]:
    """Check if a URL is accessible with retry and anti-bot handling.

    Validates IP safety before making HTTP request (SSRF protection).

    Args:
        url: URL to check.
        config: Bot configuration.
        max_retries: Maximum retry attempts.

    Returns:
        Tuple of (status_code, error_message).
        Status 0 means connection/timeout error.
    """
    # SSRF validation
    validation = validate_ip_safety(url)
    if not validation["is_safe"]:
        logger.warning("SSRF blocked: %s — %s", url, validation["rejection_reason"])
        return (0, f"SSRF blocked: {validation['rejection_reason']}")

    timeout = get_http_timeout(config)
    user_agent = get_user_agent(config)

    headers = {"User-Agent": user_agent}
    for attempt in range(max_retries):
        try:
            # Try HEAD first (faster)
            response = httpx.head(
                url, headers=headers, timeout=timeout, follow_redirects=True
            )

            # Anti-bot: retry with GET + browser headers on 403/405
            if response.status_code in (403, 405) and attempt < max_retries - 1:
                headers.update(_BROWSER_HEADERS)
                response = httpx.get(
                    url, headers=headers, timeout=timeout, follow_redirects=True
                )

            return (response.status_code, None)

        except httpx.TimeoutException:
            if attempt < max_retries - 1:
                time.sleep(1.0 * (attempt + 1))
                continue
            return (0, "Timeout after retries")

        except httpx.HTTPError as e:
            if attempt < max_retries - 1:
                time.sleep(1.0 * (attempt + 1))
                continue
            return (0, str(e))

    return (0, "Max retries exceeded")


def suggest_fix(broken_url: str) -> tuple[str | None, float]:
    """Attempt to suggest a fix for a broken link.

    Uses Wayback Machine availability API to find archived versions.

    Args:
        broken_url: The broken URL.

    Returns:
        Tuple of (suggested_url, confidence).
    """
    try:
        api_url = f"https://archive.org/wayback/available?url={broken_url}"
        response = httpx.get(api_url, timeout=10.0)
        if response.status_code == 200:
            data = response.json()
            snapshots = data.get("archived_snapshots", {})
            closest = snapshots.get("closest")
            if closest and closest.get("available"):
                return (closest["url"], 0.6)
    except (httpx.HTTPError, ValueError, KeyError):
        pass

    return (None, 0.0)


def scan_repository(
    target: TargetRepository,
    config: BotConfig,
    work_dir: Path,
) -> ScanResult:
    """Scan a cloned repository for broken links.

    Args:
        target: Target repository info.
        config: Bot configuration.
        work_dir: Path to cloned repository.

    Returns:
        ScanResult with found broken links.
    """
    broken_links: list[BrokenLink] = []
    files_scanned = 0
    links_checked = 0

    # Find all markdown files
    md_files = list(work_dir.rglob("*.md"))

    for md_file in md_files:
        try:
            content = md_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            logger.warning("Could not read: %s", md_file)
            continue

        files_scanned += 1
        rel_path = str(md_file.relative_to(work_dir))
        links = extract_links_from_markdown(content)

        for url, line_no in links:
            links_checked += 1
            status, error = check_link(url, config, max_retries=2)

            if status in _BROKEN_STATUSES:
                suggested, confidence = suggest_fix(url)
                broken_links.append(
                    make_broken_link(
                        source_file=rel_path,
                        line_number=line_no,
                        original_url=url,
                        status_code=status,
                        suggested_fix=suggested,
                        fix_confidence=confidence,
                    )
                )
            elif status == 0 and error:
                logger.info("Link error for %s: %s", url, error)

    return ScanResult(
        repository=target,
        scan_time=now_iso(),
        broken_links=broken_links,
        error=None,
        files_scanned=files_scanned,
        links_checked=links_checked,
    )
