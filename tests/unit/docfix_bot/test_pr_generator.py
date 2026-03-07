"""Tests for docfix_bot.pr_generator."""

from __future__ import annotations

from docfix_bot.models import make_broken_link
from docfix_bot.pr_generator import generate_pr_body, generate_pr_title


class TestGeneratePrTitle:
    def test_empty_list(self) -> None:
        title = generate_pr_title([])
        assert title == "fix: correct broken links"

    def test_single_link(self) -> None:
        links = [make_broken_link("README.md", 5, "https://old.com", 404)]
        title = generate_pr_title(links)
        assert "README.md" in title
        assert title.startswith("fix:")

    def test_multiple_links_same_file(self) -> None:
        links = [
            make_broken_link("README.md", 5, "https://a.com", 404),
            make_broken_link("README.md", 10, "https://b.com", 404),
        ]
        title = generate_pr_title(links)
        assert "2 broken links" in title
        assert "README.md" in title

    def test_multiple_files(self) -> None:
        links = [
            make_broken_link("README.md", 5, "https://a.com", 404),
            make_broken_link("DOCS.md", 10, "https://b.com", 404),
        ]
        title = generate_pr_title(links)
        assert "2 broken links" in title
        # Multiple files -> no specific file name in title
        assert "README.md" not in title


class TestGeneratePrBody:
    def test_contains_header(self) -> None:
        links = [make_broken_link("README.md", 5, "https://old.com", 404)]
        body = generate_pr_body(links)
        assert "## Broken Link Fix" in body

    def test_contains_table(self) -> None:
        links = [make_broken_link("README.md", 5, "https://old.com", 404)]
        body = generate_pr_body(links)
        assert "| File | Line |" in body
        assert "`README.md`" in body
        assert "https://old.com" in body
        assert "404" in body

    def test_shows_suggested_fix(self) -> None:
        links = [
            make_broken_link(
                "README.md",
                5,
                "https://old.com",
                404,
                suggested_fix="https://new.com",
            ),
        ]
        body = generate_pr_body(links)
        assert "https://new.com" in body

    def test_no_fix_placeholder(self) -> None:
        links = [make_broken_link("README.md", 5, "https://old.com", 404)]
        body = generate_pr_body(links)
        assert "_(no fix suggested)_" in body

    def test_footer(self) -> None:
        links = [make_broken_link("README.md", 5, "https://old.com", 404)]
        body = generate_pr_body(links)
        assert "Doc-Fix Bot" in body
        assert "opt out" in body

    def test_multiple_links(self) -> None:
        links = [
            make_broken_link("README.md", 5, "https://a.com", 404),
            make_broken_link("DOCS.md", 10, "https://b.com", 410),
        ]
        body = generate_pr_body(links)
        assert "https://a.com" in body
        assert "https://b.com" in body
        assert "410" in body

    def test_empty_list(self) -> None:
        body = generate_pr_body([])
        assert "## Broken Link Fix" in body
        # Table header but no data rows
        assert "| File | Line |" in body
