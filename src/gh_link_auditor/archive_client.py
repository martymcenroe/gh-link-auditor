"""Internet Archive CDX API client for dead link investigation.

Queries the Wayback Machine CDX server for archived snapshots,
fetches snapshot HTML content, and extracts titles and content summaries.

BeautifulSoup4 is optional — falls back to regex for HTML parsing.

See LLD #20 §2.4 for API specification.
"""

from __future__ import annotations

import re
import time
import urllib.error
import urllib.request
from typing import TypedDict

from gh_link_auditor.network import BackoffConfig, calculate_backoff_delay, create_backoff_config
from src.logging_config import setup_logging

logger = setup_logging("archive_client")

CDX_API_URL = "https://web.archive.org/cdx/search/cdx"

# HTTP status codes that trigger CDX retry
_CDX_RETRY_CODES: frozenset[int] = frozenset({429, 503})

# Default backoff for CDX requests: 2 retries, 1s base, low jitter
_DEFAULT_CDX_BACKOFF: BackoffConfig = create_backoff_config(
    base_delay=1.0,
    max_delay=30.0,
    max_retries=2,
    jitter_range=0.5,
)


class CDXResponse(TypedDict):
    """Parsed response from the CDX API."""

    url: str
    timestamp: str
    original: str
    mimetype: str
    statuscode: str
    digest: str
    length: str


# ---------------------------------------------------------------------------
# Internal HTTP helpers (mock targets for testing)
# ---------------------------------------------------------------------------


def _cdx_request(url: str, backoff: BackoffConfig | None = None) -> str:
    """Make a raw HTTP request to the CDX API with retry on 429/503.

    Args:
        url: Full CDX API query URL.
        backoff: Optional backoff configuration. Uses ``_DEFAULT_CDX_BACKOFF``
            when *None*.

    Returns:
        Response body as string.

    Raises:
        urllib.error.HTTPError: Re-raised after retries are exhausted.
        Exception: Any non-retryable error is raised immediately.
    """
    cfg = backoff or _DEFAULT_CDX_BACKOFF
    last_exc: Exception | None = None

    for attempt in range(cfg["max_retries"] + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "gh-link-auditor/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
                return resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            if exc.code not in _CDX_RETRY_CODES:
                raise
            last_exc = exc
            if attempt < cfg["max_retries"]:
                delay = calculate_backoff_delay(attempt, cfg)
                logger.info(
                    "CDX %d for %s — retry %d/%d in %.1fs",
                    exc.code,
                    url,
                    attempt + 1,
                    cfg["max_retries"],
                    delay,
                )
                time.sleep(delay)

    # Exhausted retries — re-raise the last error
    raise last_exc  # type: ignore[misc]


def _fetch_url_content(url: str, backoff: BackoffConfig | None = None) -> str | None:
    """Fetch URL content as a string with retry on 429/503.

    Args:
        url: URL to fetch.
        backoff: Optional backoff configuration. Uses ``_DEFAULT_CDX_BACKOFF``
            when *None*.

    Returns:
        Response body string, or None on failure.
    """
    cfg = backoff or _DEFAULT_CDX_BACKOFF
    last_exc: Exception | None = None

    for attempt in range(cfg["max_retries"] + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "gh-link-auditor/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            if exc.code not in _CDX_RETRY_CODES:
                return None
            last_exc = exc
            if attempt < cfg["max_retries"]:
                delay = calculate_backoff_delay(attempt, cfg)
                logger.info(
                    "Fetch %d for %s — retry %d/%d in %.1fs",
                    exc.code,
                    url,
                    attempt + 1,
                    cfg["max_retries"],
                    delay,
                )
                time.sleep(delay)
        except (urllib.error.URLError, OSError):
            return None

    # Exhausted retries — return None (non-fatal for content fetch)
    logger.warning(
        "Fetch exhausted %d retries for %s (last: %s)",
        cfg["max_retries"],
        url,
        last_exc,
    )
    return None


# ---------------------------------------------------------------------------
# Optional BS4 import
# ---------------------------------------------------------------------------

try:
    from bs4 import BeautifulSoup

    _HAS_BS4 = True
except ImportError:
    _HAS_BS4 = False


# ---------------------------------------------------------------------------
# ArchiveClient
# ---------------------------------------------------------------------------


class ArchiveClient:
    """Client for Internet Archive CDX API and Wayback Machine snapshots."""

    def get_latest_snapshot(self, url: str) -> CDXResponse | None:
        """Query CDX API for the most recent snapshot of a URL.

        Args:
            url: The URL to look up in the archive.

        Returns:
            Parsed CDXResponse dict, or None if no snapshot found.
        """
        fields = "url,timestamp,original,mimetype,statuscode,digest,length"
        query = f"{CDX_API_URL}?url={url}&output=text&fl={fields}&limit=1&sort=reverse"
        try:
            response = _cdx_request(query)
        except Exception:
            logger.warning("CDX API request failed for %s", url)
            return None

        response = response.strip()
        if not response:
            return None

        parts = response.split()
        if len(parts) < 7:
            logger.warning("Unexpected CDX response format: %s", response)
            return None

        return CDXResponse(
            url=parts[2],
            timestamp=parts[1],
            original=parts[2],
            mimetype=parts[3],
            statuscode=parts[4],
            digest=parts[5],
            length=parts[6],
        )

    def fetch_snapshot_content(self, snapshot_url: str) -> str | None:
        """Fetch HTML content from a Wayback Machine snapshot.

        Args:
            snapshot_url: Full Wayback Machine URL.

        Returns:
            HTML string, or None on failure.
        """
        return _fetch_url_content(snapshot_url)

    def extract_title(self, html: str) -> str | None:
        """Extract the ``<title>`` text from HTML.

        Uses BeautifulSoup4 if available, otherwise falls back to regex.

        Args:
            html: HTML string.

        Returns:
            Title text, or None if not found.
        """
        if not html:
            return None

        if _HAS_BS4:
            soup = BeautifulSoup(html, "html.parser")
            title_tag = soup.find("title")
            if title_tag and title_tag.string:
                return title_tag.string.strip()
            return None

        # Regex fallback
        match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        if match:
            text = match.group(1).strip()
            # Collapse whitespace
            text = re.sub(r"\s+", " ", text)
            return text if text else None
        return None

    def extract_content_summary(self, html: str, max_chars: int = 500) -> str | None:
        """Extract first N characters of visible text content from HTML.

        Uses BeautifulSoup4 if available, otherwise falls back to regex
        tag stripping.

        Args:
            html: HTML string.
            max_chars: Maximum characters to return.

        Returns:
            Plain-text summary, or None if no content extracted.
        """
        if not html:
            return None

        if _HAS_BS4:
            soup = BeautifulSoup(html, "html.parser")
            # Remove script and style elements
            for tag in soup(["script", "style"]):
                tag.decompose()
            text = soup.get_text(separator=" ", strip=True)
        else:
            # Regex fallback: strip tags
            text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.IGNORECASE | re.DOTALL)
            text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.IGNORECASE | re.DOTALL)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()

        if not text:
            return None

        return text[:max_chars]
