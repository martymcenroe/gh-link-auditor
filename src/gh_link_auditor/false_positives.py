"""False positive knowledge store.

Filters out URLs that are known to produce false dead-link reports.
Extensible: add new rules to the domain sets or pattern lists.

See Issues #94, #97 for specification.
"""

from __future__ import annotations

import re
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

# Domains where non-200 responses are by design (API test services).
API_TEST_DOMAINS: set[str] = {
    "httpbin.org",
    "httpbin.com",
}

# Placeholder path segments that indicate template/example URLs.
_PLACEHOLDER_PATH_RE = re.compile(
    r"(YOUR[_-]USERNAME|YOUR[_-]ORG|YOUR[_-]REPO|YOUR[_-]TOKEN"
    r"|USERNAME|OWNER|ORG_NAME|REPO_NAME)",
    re.IGNORECASE,
)

# GitHub issue/PR URL pattern.
_GITHUB_ISSUE_RE = re.compile(
    r"https?://github\.com/[^/]+/[^/]+/(issues|pull)/\d+",
)

# GitHub paths that require authentication (return 404 when not logged in).
_GITHUB_AUTH_PATHS = re.compile(
    r"https?://github\.com/[^/]+/[^/]+/"
    r"(issues/new|compare|settings|releases/new|invitations"
    r"|new|edit|delete|import|transfer)",
)


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


def is_api_test_endpoint(url: str) -> bool:
    """Check if a URL is an API test service endpoint.

    Sites like httpbin.org return non-200 by design — auth endpoints
    return 401, method-specific endpoints return 405, etc.

    Args:
        url: URL to check.

    Returns:
        True if the URL is a known API test endpoint.
    """
    hostname = (urlparse(url).hostname or "").lower()

    for domain in API_TEST_DOMAINS:
        if hostname == domain or hostname.endswith(f".{domain}"):
            return True

    return False


def is_placeholder_path(url: str) -> bool:
    """Check if a URL contains placeholder path segments.

    Template URLs like https://github.com/YOUR-USERNAME/repo are
    examples in documentation, not real links.

    Args:
        url: URL to check.

    Returns:
        True if the URL contains placeholder segments.
    """
    path = urlparse(url).path
    return bool(_PLACEHOLDER_PATH_RE.search(path))


def is_github_issue_404(url: str, http_status: int | None) -> bool:
    """Check if a GitHub issue/PR URL returning 404 is likely private or transferred.

    GitHub returns 404 for private, transferred, or deleted issues.
    These are not dead links — the content exists but is access-controlled.

    Args:
        url: URL to check.
        http_status: HTTP status code.

    Returns:
        True if this is a GitHub issue/PR 404.
    """
    if http_status != 404:
        return False

    return bool(_GITHUB_ISSUE_RE.match(url))


def is_github_auth_required(url: str, http_status: int | None) -> bool:
    """Check if a GitHub URL requires authentication.

    URLs like /issues/new, /compare, /settings return 404 when not logged in
    but are valid authenticated endpoints.

    Args:
        url: URL to check.
        http_status: HTTP status code.

    Returns:
        True if this is a GitHub auth-required URL.
    """
    if http_status != 404:
        return False

    return bool(_GITHUB_AUTH_PATHS.match(url))


def is_false_positive(url: str, http_status: int | None = None) -> bool:
    """Master check: is this URL a known false positive?

    Args:
        url: URL to check.
        http_status: HTTP status code (optional, needed for status-based checks).

    Returns:
        True if the URL should be filtered out.
    """
    if is_placeholder_url(url):
        return True

    if is_placeholder_path(url):
        return True

    if is_api_test_endpoint(url):
        return True

    if http_status is not None:
        if is_bot_blocked(url, http_status):
            return True
        if is_github_issue_404(url, http_status):
            return True
        if is_github_auth_required(url, http_status):
            return True

    return False
