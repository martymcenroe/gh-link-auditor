"""Tests for sitemap-based same-site page discovery.

See Issue #106 for specification.
"""

from __future__ import annotations

from unittest.mock import patch

from gh_link_auditor.sitemap_searcher import (
    _extract_loc_urls,
    _path_segments,
    _slugify,
    fetch_sitemap,
    search_sitemap_for_match,
)


class TestPathSegments:
    """Tests for _path_segments()."""

    def test_simple_path(self) -> None:
        assert _path_segments("/docs/advanced/usage") == ["docs", "advanced", "usage"]

    def test_trailing_slash(self) -> None:
        assert _path_segments("/advanced/") == ["advanced"]

    def test_root(self) -> None:
        assert _path_segments("/") == []

    def test_empty(self) -> None:
        assert _path_segments("") == []


class TestSlugify:
    """Tests for _slugify()."""

    def test_basic_title(self) -> None:
        assert _slugify("Advanced Usage") == "advanced-usage"

    def test_special_characters(self) -> None:
        assert _slugify("HTTP/2 — The Basics!") == "http2-the-basics"

    def test_empty(self) -> None:
        assert _slugify("") == ""


class TestExtractLocUrls:
    """Tests for _extract_loc_urls()."""

    def test_extracts_urls(self) -> None:
        xml = """<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://example.com/page1</loc></url>
            <url><loc>https://example.com/page2</loc></url>
        </urlset>"""
        urls = _extract_loc_urls(xml)
        assert urls == ["https://example.com/page1", "https://example.com/page2"]

    def test_empty_sitemap(self) -> None:
        assert _extract_loc_urls("<urlset></urlset>") == []


class TestSearchSitemapForMatch:
    """Tests for search_sitemap_for_match()."""

    def test_finds_matching_path_segments(self) -> None:
        urls = [
            "https://example.com/docs/quickstart",
            "https://example.com/docs/advanced/usage",
            "https://example.com/about",
        ]
        matches = search_sitemap_for_match(urls, "/docs/advanced/", archive_title="Advanced Usage")
        assert len(matches) > 0
        assert "https://example.com/docs/advanced/usage" in matches

    def test_title_slug_match(self) -> None:
        urls = [
            "https://example.com/guide/advanced-usage",
            "https://example.com/guide/installation",
        ]
        matches = search_sitemap_for_match(urls, "/old/path/", archive_title="Advanced Usage")
        assert "https://example.com/guide/advanced-usage" in matches

    def test_excludes_exact_original(self) -> None:
        urls = [
            "https://example.com/advanced/",
            "https://example.com/advanced/new-location",
        ]
        matches = search_sitemap_for_match(urls, "/advanced/", archive_title="Advanced")
        # Should NOT include the original path
        assert "https://example.com/advanced/" not in matches

    def test_empty_sitemap_returns_empty(self) -> None:
        assert search_sitemap_for_match([], "/path/", archive_title="Title") == []

    def test_no_title_uses_path_only(self) -> None:
        urls = [
            "https://example.com/docs/advanced/usage",
            "https://example.com/about",
        ]
        matches = search_sitemap_for_match(urls, "/docs/advanced/")
        # Should still find path-segment matches
        assert len(matches) > 0

    def test_respects_max_candidates(self) -> None:
        urls = [f"https://example.com/docs/page{i}" for i in range(20)]
        matches = search_sitemap_for_match(urls, "/docs/something", max_candidates=3)
        assert len(matches) <= 3

    def test_best_match_first(self) -> None:
        urls = [
            "https://example.com/unrelated",
            "https://example.com/docs/advanced-usage",
            "https://example.com/docs/something-else",
        ]
        matches = search_sitemap_for_match(urls, "/docs/advanced/", archive_title="Advanced Usage")
        if matches:
            # The one with both path segment and title match should rank highest
            assert "advanced-usage" in matches[0]


class TestFetchSitemap:
    """Tests for fetch_sitemap()."""

    def test_fetches_and_parses(self) -> None:
        sitemap_xml = """<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://example.com/page1</loc></url>
            <url><loc>https://example.com/page2</loc></url>
        </urlset>"""

        def fake_fetch(url):
            if "sitemap.xml" in url:
                return sitemap_xml
            return None

        with patch("gh_link_auditor.sitemap_searcher._fetch_url", side_effect=fake_fetch):
            urls = fetch_sitemap("example.com")

        assert urls == ["https://example.com/page1", "https://example.com/page2"]

    def test_handles_sitemap_index(self) -> None:
        index_xml = """<?xml version="1.0"?>
        <sitemapindex>
            <sitemap><loc>https://example.com/sitemap1.xml</loc></sitemap>
        </sitemapindex>"""

        child_xml = """<?xml version="1.0"?>
        <urlset>
            <url><loc>https://example.com/child-page</loc></url>
        </urlset>"""

        def fake_fetch(url):
            if "sitemap.xml" in url and "sitemap1" not in url:
                return index_xml
            if "sitemap1.xml" in url:
                return child_xml
            return None

        with patch("gh_link_auditor.sitemap_searcher._fetch_url", side_effect=fake_fetch):
            urls = fetch_sitemap("example.com")

        assert "https://example.com/child-page" in urls

    def test_returns_empty_on_no_sitemap(self) -> None:
        with patch("gh_link_auditor.sitemap_searcher._fetch_url", return_value=None):
            urls = fetch_sitemap("example.com")
        assert urls == []

    def test_handles_fetch_failure(self) -> None:
        with patch("gh_link_auditor.sitemap_searcher._fetch_url", return_value=None):
            urls = fetch_sitemap("nonexistent.example.com")
        assert urls == []
