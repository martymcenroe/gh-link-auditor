"""False positive knowledge store.

Filters out URLs that are known to produce false dead-link reports.
Extensible: add new rules to SKIP_DOMAINS or BOT_BLOCKED_DOMAINS.

See Issue #94 for specification.
"""

from __future__ import annotations

from urllib.parse import urlparse

# Domains that are intentionally fake / placeholder — never real links.
SKIP_DOMAINS: set[str] = {
    "example.com",
    "example.org",
    "example.net",
    "example.edu",
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
}

# Domains that return 403 to bots but work fine in browsers.
BOT_BLOCKED_DOMAINS: set[str] = {
    "stackoverflow.com",
    "stackexchange.com",
    "security.stackexchange.com",
    "serverfault.com",
    "superuser.com",
    "askubuntu.com",
    "mathoverflow.net",
}


def is_placeholder_url(url: str) -> bool:
    """Check if a URL uses a known placeholder/example domain.

    These URLs are intentionally fake and should never be reported as dead.

    Args:
        url: URL to check.

    Returns:
        True if the URL is a placeholder.
    """
    hostname = (urlparse(url).hostname or "").lower()

    for domain in SKIP_DOMAINS:
        if hostname == domain or hostname.endswith(f".{domain}"):
            return True

    return False


def is_bot_blocked(url: str, http_status: int | None) -> bool:
    """Check if a URL failure is likely due to bot blocking, not a dead link.

    Args:
        url: The URL that was checked.
        http_status: HTTP status code returned (e.g. 403).

    Returns:
        True if the failure is likely bot blocking.
    """
    if http_status != 403:
        return False

    hostname = (urlparse(url).hostname or "").lower()

    for domain in BOT_BLOCKED_DOMAINS:
        if hostname == domain or hostname.endswith(f".{domain}"):
            return True

    return False


def is_false_positive(url: str, http_status: int | None = None) -> bool:
    """Master check: is this URL a known false positive?

    Args:
        url: URL to check.
        http_status: HTTP status code (optional, needed for bot-blocked check).

    Returns:
        True if the URL should be filtered out.
    """
    if is_placeholder_url(url):
        return True

    if http_status is not None and is_bot_blocked(url, http_status):
        return True

    return False
