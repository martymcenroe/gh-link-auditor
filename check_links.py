"""Link checking utility for gh-link-auditor.

Extracts and validates HTTP/HTTPS URLs from files, reporting status
via structured logging. See LLD #11 for design rationale.
Anti-bot fallback via network.py integration per LLD #1.
"""

import re
from typing import TypedDict

from gh_link_auditor.network import check_url as network_check_url
from gh_link_auditor.network import create_backoff_config, create_request_config, should_retry
from src.logging_config import setup_logging

# LLD §2.5 step 3.2: Module-level logger
logger = setup_logging("check_links")


# ---------------------------------------------------------------------------
# LLD #1 — Anti-bot fallback data structures and helpers
# ---------------------------------------------------------------------------


class LinkCheckResult(TypedDict):
    """Result of a link check with fallback metadata."""

    url: str
    status_code: int | None
    method_used: str
    fallback_used: bool
    error: str | None


def should_fallback_to_get(status_code: int) -> bool:
    """Check if a HEAD response should trigger a GET fallback.

    Delegates to ``network.should_retry`` and returns the ``try_get_fallback`` flag.

    Args:
        status_code: HTTP status code from a HEAD request.

    Returns:
        ``True`` if the status code warrants a GET fallback (e.g. 403, 405).
    """
    _retry, try_get = should_retry(status_code, None)
    return try_get


def log_fallback_attempt(url: str, head_status: int) -> None:
    """Log that a GET fallback is being attempted for a URL.

    Args:
        url: The URL being checked.
        head_status: The HTTP status code received from the HEAD request.
    """
    logger.info("HEAD returned %d for %s — falling back to GET", head_status, url)


def check_link_with_fallback(url: str, timeout: int = 10) -> LinkCheckResult:
    """Check a URL using network.check_url with HEAD→GET fallback.

    Creates a ``RequestConfig`` with ``verify_ssl=False`` (matching the original
    ``check_links`` behaviour) and delegates to ``network.check_url``.

    Args:
        url: The URL to check.
        timeout: Request timeout in seconds.

    Returns:
        A ``LinkCheckResult`` with status and fallback metadata.
    """
    req_cfg = create_request_config(timeout=float(timeout), verify_ssl=False)
    result = network_check_url(url, request_config=req_cfg)

    fallback_used = result["method"] == "GET"
    if fallback_used:
        log_fallback_attempt(url, 0)

    return LinkCheckResult(
        url=result["url"],
        status_code=result["status_code"],
        method_used=result["method"],
        fallback_used=fallback_used,
        error=result["error"],
    )


def find_urls(filepath: str) -> list[str]:
    """Extracts all HTTP/HTTPS URLs from a file."""
    logger.info("Locating URLs in %s", filepath)
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        logger.error("Could not read file: %s", e)
        return []

    # Regex to find URLs, including those in markdown parens
    # It avoids matching the final parenthesis if it's part of the markdown
    url_regex = re.compile(r"https?://[a-zA-Z0-9./?_&%=\-~:#]+")

    urls = url_regex.findall(content)
    unique_urls = sorted(list(set(urls)))
    logger.info("Found %d unique URLs.", len(unique_urls))
    return unique_urls


def check_url(url: str, retries: int = 2) -> str:
    """Check a single URL and return a human-readable status string.

    Delegates to :func:`check_link_with_fallback` (which uses ``network.check_url``
    with HEAD→GET fallback) and formats the result to match the original output.

    Args:
        url: The URL to validate.
        retries: Maximum number of retries (maps to ``backoff_config.max_retries``).

    Returns:
        A formatted status string (e.g. ``"[  OK  ] (Code: 200) - https://…"``).
    """
    req_cfg = create_request_config(timeout=10.0, verify_ssl=False)
    backoff_cfg = create_backoff_config(max_retries=retries)
    result = network_check_url(url, request_config=req_cfg, backoff_config=backoff_cfg)

    if result["method"] == "GET":
        log_fallback_attempt(url, 0)

    status = result["status"]
    code = result["status_code"]

    if status == "ok":
        return f"[  OK  ] (Code: {code}) - {url}"
    if status == "timeout":
        return f"[ TIMEOUT ] - {url}"
    if status == "disconnected":
        return f"[ DISCONNECTED ] - {url}"
    if status == "error":
        return f"[ ERROR ] (Code: {code}) - {url}"
    if status == "failed":
        return f"[ FAILED ] (Reason: {result['error']}) - {url}"
    return f"[ INVALID ] (Error: {result['error']}) - {url}"


def main():
    """Main function to check all URLs in README.md."""
    filepath = "README.md"
    urls_to_check = find_urls(filepath)

    if not urls_to_check:
        logger.info("No URLs found to check.")
        return

    logger.info("Starting URL Validation")

    error_count = 0
    for url in urls_to_check:
        status = check_url(url)
        if "ERROR" in status or "FAILED" in status or "TIMEOUT" in status or "INVALID" in status:
            logger.warning(status)
            error_count += 1
        else:
            logger.info(status)

    logger.info("Validation Complete")
    if error_count == 0:
        logger.info("All links are valid.")
    else:
        logger.warning("Found %d potential issues.", error_count)


if __name__ == "__main__":
    main()
