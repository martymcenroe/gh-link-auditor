"""Shared test fixtures for gh-link-auditor."""

import pytest


@pytest.fixture
def sample_markdown(tmp_path):
    """Create a temporary markdown file with sample URLs."""
    content = """# Test Document

Check out [Example](https://example.com) and [Python](https://www.python.org).

Broken link: [Missing](https://httpbin.org/status/404)
"""
    md_file = tmp_path / "test.md"
    md_file.write_text(content)
    return str(md_file)


@pytest.fixture
def empty_markdown(tmp_path):
    """Create a temporary markdown file with no URLs."""
    md_file = tmp_path / "empty.md"
    md_file.write_text("# No links here\n\nJust plain text.\n")
    return str(md_file)
