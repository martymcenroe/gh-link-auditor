"""Whole-domain rebrand / migration detection (#262).

When a dead URL's host has been entirely rebranded (e.g.
``play.picoctf.org -> learn.cylabacademy.org``), the per-URL probe sees
nothing -- the original domain is gone. LinkDetective's URL-level
redirect handling can't recover the new URL because there's no live
redirect chain to follow.

This module ships a hand-curated sunset table mapping known-rebranded
hosts to their canonical successor. ``find_rebrand_target`` returns a
candidate replacement URL (path preserved) when the dead URL's host is
in the table.

The audit (#262 / 2026-05-23) named these as high-value PR opportunities
that are currently invisible. The table starts small with the operator's
named examples; new entries are added via PR as the operator discovers
them in scan output.

Adding a host:

1. Confirm via browser that the OLD host is genuinely dead or auto-
   redirects to the new host. If the old host still responds, the
   existing URL-level redirect resolver handles it.
2. Confirm the NEW host serves the same content class (docs, blog,
   tutorial, etc.) -- different content domains aren't a fair
   replacement even if the company is the same.
3. Add the entry below with a short ``reason`` and ``since`` year.
4. Add a test in ``tests/unit/test_domain_rebrand.py``.

A ``replacement_host=None`` entry means the host shut down with no
successor (gfycat, hipchat). The pipeline records the diagnostic but
emits no candidate -- removal proposals must still go through
operator review (see #261 / temporary-failure routing).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from urllib.parse import urlparse, urlunparse


@dataclass(frozen=True)
class SunsetEntry:
    """A single entry in the sunset table."""

    old_host: str
    replacement_host: str | None
    since: str  # year as string
    reason: str = ""


SUNSET_DOMAINS: Final[dict[str, SunsetEntry]] = {
    # picoCTF tutorial site -> CyLab Academy (Carnegie Mellon).
    # Original observation: 132 findings with None status, audit #262.
    "play.picoctf.org": SunsetEntry(
        old_host="play.picoctf.org",
        replacement_host="learn.cylabacademy.org",
        since="2023",
        reason="picoCTF platform migrated to CyLab Academy",
    ),
    # Gitter chat acquired by Element / Matrix.org (2022).
    "gitter.im": SunsetEntry(
        old_host="gitter.im",
        replacement_host="element.io",
        since="2022",
        reason="acquired by Element; chat lives in Matrix rooms",
    ),
    # SignalFx APM acquired by Splunk; docs moved.
    "docs.signalfx.com": SunsetEntry(
        old_host="docs.signalfx.com",
        replacement_host="docs.splunk.com",
        since="2022",
        reason="SignalFx acquired by Splunk; docs subdomain consolidated",
    ),
    "signalfx.com": SunsetEntry(
        old_host="signalfx.com",
        replacement_host="splunk.com",
        since="2022",
        reason="SignalFx acquired by Splunk",
    ),
    # HipChat shut down (Atlassian sold to Slack).
    "hipchat.com": SunsetEntry(
        old_host="hipchat.com",
        replacement_host=None,
        since="2019",
        reason="shutdown; users migrated to Slack but no canonical successor URL",
    ),
    # Gfycat shut down 2023; archived only.
    "gfycat.com": SunsetEntry(
        old_host="gfycat.com",
        replacement_host=None,
        since="2023",
        reason="shutdown; no replacement",
    ),
}


def find_rebrand_target(url: str) -> str | None:
    """Return a candidate replacement URL when ``url``'s host is in the
    sunset table and has a ``replacement_host``. Path / query / fragment
    are preserved on the new host.

    Returns ``None`` when:

    - the host is not in the sunset table, OR
    - the host is in the table but its ``replacement_host`` is ``None``
      (the service shut down with no successor).

    Callers can use ``find_sunset_entry`` for the full record when the
    "no successor" case is also actionable (operator-driven removal).
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if not host:
        return None
    entry = SUNSET_DOMAINS.get(host)
    if entry is None:
        return None
    if entry.replacement_host is None:
        return None
    # Preserve scheme, path, params, query, fragment; swap netloc.
    return urlunparse(
        (
            parsed.scheme or "https",
            entry.replacement_host,
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


def find_sunset_entry(url: str) -> SunsetEntry | None:
    """Return the full SunsetEntry for ``url``'s host, or None.

    Useful for the operator-facing "this host is sunsetted but had no
    successor" diagnostic. ``find_rebrand_target`` skips no-successor
    entries because they can't produce a candidate URL.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if not host:
        return None
    return SUNSET_DOMAINS.get(host)


def is_sunsetted_host(url: str) -> bool:
    """True if the URL's host is in the sunset table (with or without
    a successor)."""
    return find_sunset_entry(url) is not None


__all__ = [
    "SUNSET_DOMAINS",
    "SunsetEntry",
    "find_rebrand_target",
    "find_sunset_entry",
    "is_sunsetted_host",
]
