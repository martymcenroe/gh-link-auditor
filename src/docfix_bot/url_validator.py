"""SSRF protection and URL safety validation.

See LLD #2 §2.4 for url_validator specification.
Reuses SSRF infrastructure from gh_link_auditor.redirect_resolver.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urlparse

from docfix_bot.models import URLValidationResult

logger = logging.getLogger(__name__)

# Private/reserved IP ranges to block (SSRF protection)
_PRIVATE_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),  # Link-local / AWS metadata
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]


def is_private_ip(ip_str: str) -> bool:
    """Check if an IP address is in a private/reserved range.

    Args:
        ip_str: IP address string.

    Returns:
        True if IP is private/reserved.
    """
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # Invalid IPs treated as unsafe

    return any(ip in network for network in _PRIVATE_NETWORKS)


def validate_ip_safety(url: str) -> URLValidationResult:
    """Validate URL hostname against private IP ranges.

    Resolves the URL's hostname to an IP address and checks
    that it does not point to a private/local network.

    Args:
        url: URL to validate.

    Returns:
        URLValidationResult with safety status.
    """
    parsed = urlparse(url)
    hostname = parsed.hostname

    if not hostname:
        return URLValidationResult(
            url=url,
            is_safe=False,
            resolved_ip=None,
            rejection_reason="No hostname in URL",
        )

    try:
        addr_infos = socket.getaddrinfo(hostname, 443)
    except socket.gaierror:
        return URLValidationResult(
            url=url,
            is_safe=False,
            resolved_ip=None,
            rejection_reason=f"DNS resolution failed for {hostname}",
        )

    for family, _type, _proto, _canonname, sockaddr in addr_infos:
        ip_str = sockaddr[0]
        if is_private_ip(ip_str):
            logger.warning("SSRF blocked: %s resolves to private IP %s", url, ip_str)
            return URLValidationResult(
                url=url,
                is_safe=False,
                resolved_ip=ip_str,
                rejection_reason=f"Private IP: {ip_str}",
            )

    # Use the first resolved IP for the result
    first_ip = addr_infos[0][4][0] if addr_infos else None
    return URLValidationResult(
        url=url,
        is_safe=True,
        resolved_ip=first_ip,
        rejection_reason=None,
    )
