"""Tests for bulk_scan.inventory pure-function bits (#218)."""

from __future__ import annotations

from gh_link_auditor.bulk_scan.inventory import (
    _clean_url_tail,
    extract_urls_from_text,
    filter_url,
)


class TestCleanUrlTail:
    def test_strips_trailing_period(self) -> None:
        assert _clean_url_tail("https://example.com.") == "https://example.com"

    def test_balanced_parens_preserved(self) -> None:
        assert _clean_url_tail("https://en.wikipedia.org/wiki/Foo_(bar)") == "https://en.wikipedia.org/wiki/Foo_(bar)"

    def test_unbalanced_trailing_paren_stripped(self) -> None:
        assert _clean_url_tail("https://example.com/foo)") == "https://example.com/foo"


class TestExtractUrls:
    def test_simple(self) -> None:
        urls = extract_urls_from_text("see https://numpy.org/ for more")
        assert urls == [("https://numpy.org/", 1)]

    def test_skips_fenced_code(self) -> None:
        text = "outside https://a.com\n```\nfenced https://b.com\n```\nafter https://c.com"
        urls = [u for u, _ in extract_urls_from_text(text)]
        assert "https://a.com" in urls
        assert "https://c.com" in urls
        assert "https://b.com" not in urls

    def test_skips_indented_code(self) -> None:
        text = "ok https://a.com\n    https://indented.com\nback https://b.com"
        urls = [u for u, _ in extract_urls_from_text(text)]
        assert "https://indented.com" not in urls
        assert "https://a.com" in urls
        assert "https://b.com" in urls

    def test_line_numbers_correct(self) -> None:
        text = "line1\nhttps://x.com line2\n\nhttps://y.com line4"
        urls = extract_urls_from_text(text)
        nums = {u: ln for u, ln in urls}
        assert nums["https://x.com"] == 2
        assert nums["https://y.com"] == 4


class TestFilterUrl:
    def test_stackoverflow_filtered(self) -> None:
        assert filter_url("https://stackoverflow.com/a/1") is False

    def test_example_com_filtered(self) -> None:
        assert filter_url("https://example.com/") is False

    def test_httpbin_filtered(self) -> None:
        assert filter_url("https://httpbin.org/get") is False

    def test_real_url_passes(self) -> None:
        assert filter_url("https://numpy.org/") is True

    def test_github_passes(self) -> None:
        assert filter_url("https://github.com/foo/bar") is True

    def test_bracketed_bare_url_skipped(self) -> None:
        # #227 — extracted-from-Markdown URL with unclosed `[` would crash
        # urlparse with "Invalid IPv6 URL"; filter_url must return False
        # to keep the rest of the repo's inventory alive.
        assert filter_url("https://[unclosed") is False

    def test_nfkc_bad_netloc_skipped(self) -> None:
        # #227 — Chinese full-width punctuation in netloc fails NFKC.
        assert filter_url("https://visualstudio.microsoft.com)：用于编译") is False
