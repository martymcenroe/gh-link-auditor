"""Unit tests for URL extraction from files."""

from check_links import find_urls


class TestFindUrls:
    def test_extracts_urls_from_markdown(self, sample_markdown):
        urls = find_urls(sample_markdown)
        assert "https://example.com" in urls
        assert "https://www.python.org" in urls

    def test_returns_unique_sorted_urls(self, tmp_path):
        content = "https://b.com https://a.com https://b.com"
        md = tmp_path / "dups.md"
        md.write_text(content)
        urls = find_urls(str(md))
        assert urls == ["https://a.com", "https://b.com"]

    def test_returns_empty_for_no_urls(self, empty_markdown):
        urls = find_urls(empty_markdown)
        assert urls == []

    def test_returns_empty_for_missing_file(self):
        urls = find_urls("nonexistent_file.md")
        assert urls == []

    def test_extracts_http_and_https(self, tmp_path):
        content = "http://insecure.com https://secure.com"
        md = tmp_path / "mixed.md"
        md.write_text(content)
        urls = find_urls(str(md))
        assert "http://insecure.com" in urls
        assert "https://secure.com" in urls
