"""URL pattern construction via domain + title slugification.

Generates candidate replacement URLs from a domain, archived page title,
and original URL path. Probes candidates for liveness.

See LLD #20 §2.4 for API specification.
"""

from __future__ import annotations

import re

from gh_link_auditor.network import check_url


class URLHeuristic:
    """Construct and probe candidate URLs from domain + title patterns."""

    PATH_PREFIXES: list[str] = ["/docs/", "/guide/", "/getting-started/", "/tutorials/", "/blog/"]
    PATH_SWAPS: dict[str, list[str]] = {
        "/docs/": ["/documentation/"],
        "/guide/": ["/guides/"],
        "/tutorial/": ["/tutorials/"],
    }

    def slugify(self, title: str) -> str:
        """Convert title to kebab-case URL slug.

        Lowercases, removes non-alphanumeric characters (except spaces/hyphens),
        replaces spaces with hyphens, and collapses consecutive hyphens.

        Args:
            title: Page title text.

        Returns:
            Kebab-case slug string.
        """
        slug = title.lower().strip()
        slug = re.sub(r"[^a-z0-9\s-]", "", slug)
        slug = re.sub(r"[\s]+", "-", slug)
        slug = re.sub(r"-{2,}", "-", slug)
        slug = slug.strip("-")
        return slug

    def generate_candidates(self, domain: str, title: str, original_path: str) -> list[str]:
        """Generate candidate URLs from domain + slugified title + path patterns.

        Constructs URLs by combining the domain with the slugified title
        under various path prefixes, plus path-swap variants of the original path.

        Args:
            domain: Target domain (e.g. ``"example.com"``).
            title: Archived page title for slugification.
            original_path: Original URL path for swap-based variants.

        Returns:
            List of candidate URL strings (https scheme).
        """
        slug = self.slugify(title)
        if not slug:
            return []

        candidates: list[str] = []
        base = f"https://{domain}"

        # Slug under each path prefix
        for prefix in self.PATH_PREFIXES:
            candidates.append(f"{base}{prefix}{slug}")

        # Slug at root
        candidates.append(f"{base}/{slug}")

        # Path-swap variants based on original path
        for old, replacements in self.PATH_SWAPS.items():
            if old in original_path:
                for new in replacements:
                    swapped = original_path.replace(old, new, 1)
                    candidates.append(f"{base}{swapped}")

        # Version variants of original path
        version_variants = self._generate_version_variants(original_path)
        for variant in version_variants:
            candidates.append(f"{base}{variant}")

        return candidates

    def probe_candidates(self, candidates: list[str], max_results: int = 3) -> list[str]:
        """Probe candidate URLs for liveness.

        Checks each candidate via HTTP and returns up to ``max_results``
        URLs that respond with a 2xx status code.

        Args:
            candidates: List of URL strings to probe.
            max_results: Maximum number of live URLs to return.

        Returns:
            List of live URL strings (at most ``max_results``).
        """
        live: list[str] = []
        for url in candidates:
            if len(live) >= max_results:
                break
            result = check_url(url)
            if result.get("status") == "ok":
                live.append(url)
        return live

    def _generate_version_variants(self, path: str) -> list[str]:
        """Generate version-incremented path variants.

        For paths containing ``/v1/``, ``/v2/``, etc., generates variants
        with incremented versions and a ``/latest/`` variant.

        Args:
            path: Original URL path.

        Returns:
            List of variant paths, or empty list if no version found.
        """
        match = re.search(r"/v(\d+)/", path)
        if not match:
            return []

        current = int(match.group(1))
        variants: list[str] = []

        # Generate v(n+1) and v(n+2)
        for bump in (1, 2):
            new_version = current + bump
            variant = path[: match.start()] + f"/v{new_version}/" + path[match.end() :]
            variants.append(variant)

        # /latest/ variant
        latest = path[: match.start()] + "/latest/" + path[match.end() :]
        variants.append(latest)

        return variants
