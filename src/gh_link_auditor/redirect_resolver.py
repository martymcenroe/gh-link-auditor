"""Redirect chain follower with SSRF protection.

Follows HTTP redirect chains (301/302/307/308) up to MAX_REDIRECTS hops,
validates each hop against an SSRF denylist before connection, and tests
common URL mutations.

See LLD #20 §2.4 for API specification.
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.error
import urllib.request
from urllib.parse import urlparse

from src.logging_config import setup_logging

logger = setup_logging("redirect_resolver")

# Redirect status codes we follow
_REDIRECT_CODES = {301, 302, 307, 308}

# SSRF denylist — private/reserved IP ranges (LLD §7.1)
_PRIVATE_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]


class SSRFBlocked(Exception):
    """Raised when a URL resolves to a private/reserved IP range."""


# ---------------------------------------------------------------------------
# Internal HTTP helper (mock target for testing)
# ---------------------------------------------------------------------------


def _http_head(url: str) -> dict:
    """Make a HEAD request and return status_code + Location header.

    Args:
        url: URL to check.

    Returns:
        Dict with ``status_code`` (int) and ``location`` (str | None).
    """
    try:
        req = urllib.request.Request(
            url,
            method="HEAD",
            headers={
                "User-Agent": "gh-link-auditor/1.0",
            },
        )
        # Don't follow redirects automatically
        opener = urllib.request.build_opener(urllib.request.HTTPHandler, urllib.request.HTTPSHandler)

        class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        opener = urllib.request.build_opener(NoRedirectHandler)
        resp = opener.open(req, timeout=10)
        return {"status_code": resp.status, "location": resp.headers.get("Location")}
    except urllib.error.HTTPError as e:
        return {"status_code": e.code, "location": e.headers.get("Location")}
    except (urllib.error.URLError, OSError):
        return {"status_code": None, "location": None}


# ---------------------------------------------------------------------------
# RedirectResolver
# ---------------------------------------------------------------------------


class RedirectResolver:
    """Follow redirect chains with SSRF protection."""

    MAX_REDIRECTS: int = 10

    def follow_redirects(self, url: str) -> tuple[str | None, list[str]]:
        """Follow redirect chain, return (final_url, chain_log).

        Returns ``(None, log)`` if no redirect found, the chain exceeds
        MAX_REDIRECTS, or the final destination is not live (2xx).

        Args:
            url: Starting URL to follow.

        Returns:
            Tuple of (final_url or None, list of log entries).
        """
        log: list[str] = []
        current = url
        visited: set[str] = set()

        for hop in range(self.MAX_REDIRECTS):
            # SSRF check before each hop
            parsed = urlparse(current)
            hostname = parsed.hostname
            if hostname:
                try:
                    self._validate_not_private_ip(hostname)
                except SSRFBlocked:
                    log.append(f"SSRF blocked: {current}")
                    return None, log

            if current in visited:
                log.append(f"Redirect loop detected at {current}")
                return None, log
            visited.add(current)

            result = _http_head(current)
            code = result["status_code"]
            location = result["location"]

            if code in _REDIRECT_CODES and location:
                log.append(f"{code} {current} -> {location}")
                current = location
                continue

            # Not a redirect — check if we actually followed any redirects
            if hop == 0:
                log.append("No redirect chain detected")
                return None, log

            # We followed redirects and landed here
            if code is not None and 200 <= code < 400:
                log.append(f"Final destination: {current} ({code})")
                return current, log

            log.append(f"Redirect chain ended at {current} (status {code})")
            return None, log

        log.append(f"Max redirects ({self.MAX_REDIRECTS}) exceeded")
        return None, log

    def test_url_mutations(self, url: str) -> list[tuple[str, str]]:
        """Test common URL mutations, return list of (live_url, mutation_type).

        Mutations tested:
        - Trailing slash toggle
        - http -> https upgrade
        - www prefix toggle

        Args:
            url: Dead URL to mutate.

        Returns:
            List of (live_url, mutation_type) tuples.
        """
        mutations: list[tuple[str, str]] = []
        parsed = urlparse(url)

        # Trailing slash toggle
        if url.endswith("/"):
            candidate = url.rstrip("/")
            mutation_type = "remove_trailing_slash"
        else:
            candidate = url + "/"
            mutation_type = "add_trailing_slash"

        result = _http_head(candidate)
        if result["status_code"] is not None and 200 <= result["status_code"] < 400:
            mutations.append((candidate, mutation_type))

        # http -> https upgrade
        if parsed.scheme == "http":
            https_url = "https" + url[4:]
            result = _http_head(https_url)
            if result["status_code"] is not None and 200 <= result["status_code"] < 400:
                mutations.append((https_url, "http_to_https"))

        # www prefix toggle
        if parsed.hostname and parsed.hostname.startswith("www."):
            no_www = url.replace("://www.", "://", 1)
            result = _http_head(no_www)
            if result["status_code"] is not None and 200 <= result["status_code"] < 400:
                mutations.append((no_www, "remove_www"))
        elif parsed.hostname and not parsed.hostname.startswith("www."):
            with_www = url.replace("://", "://www.", 1)
            result = _http_head(with_www)
            if result["status_code"] is not None and 200 <= result["status_code"] < 400:
                mutations.append((with_www, "add_www"))

        return mutations

    def verify_live(self, url: str) -> bool:
        """Check if URL returns a 2xx status code.

        Args:
            url: URL to check.

        Returns:
            True if the URL responds with 2xx.
        """
        try:
            result = _http_head(url)
            return result["status_code"] is not None and 200 <= result["status_code"] < 300
        except Exception:
            return False

    def _validate_not_private_ip(self, hostname: str) -> bool:
        """Resolve hostname and validate against SSRF denylist.

        Pre-connection validation: resolves the hostname via
        ``socket.getaddrinfo()`` and checks all returned IPs
        against the private network denylist.

        Args:
            hostname: Hostname to resolve and validate.

        Returns:
            True if all resolved IPs are public.

        Raises:
            SSRFBlocked: If any resolved IP is in a private/reserved range.
        """
        try:
            addr_infos = socket.getaddrinfo(hostname, 443)
        except socket.gaierror:
            raise SSRFBlocked(f"Cannot resolve hostname: {hostname}")

        for family, type_, proto, canonname, sockaddr in addr_infos:
            ip_str = sockaddr[0]
            try:
                ip = ipaddress.ip_address(ip_str)
            except ValueError:
                continue

            for network in _PRIVATE_NETWORKS:
                if ip in network:
                    raise SSRFBlocked(f"SSRF blocked: {hostname} resolves to private IP {ip_str}")

        return True
