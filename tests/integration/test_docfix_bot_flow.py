"""DocFix Bot flow integration tests.

Tests scan-to-fix workflow using real objects with patched HTTP.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from docfix_bot.models import make_broken_link
from docfix_bot.pr_generator import generate_pr_body, generate_pr_title


@pytest.mark.integration
class TestDocFixBotFlow:
    """Scan → PR generation flow tests."""

    def test_pr_generation_from_broken_links(self) -> None:
        """generate_pr_title + body from real BrokenLink objects."""
        links = [
            make_broken_link(
                "README.md",
                5,
                "https://old.com/docs",
                404,
                suggested_fix="https://new.com/docs",
                fix_confidence=0.95,
            ),
            make_broken_link(
                "CONTRIBUTING.md",
                10,
                "https://gone.com/guide",
                404,
                suggested_fix="https://archive.org/guide",
                fix_confidence=0.7,
            ),
        ]

        title = generate_pr_title(links)
        body = generate_pr_body(links)

        assert isinstance(title, str)
        assert len(title) > 0
        assert "2 broken links" in title
        assert isinstance(body, str)
        assert len(body) > 0

    def test_full_fix_workflow_dry_run(self, tmp_path: Path) -> None:
        """apply_fixes modifies files in tmp_path."""
        from docfix_bot.git_workflow import apply_fixes

        readme = tmp_path / "README.md"
        readme.write_text("# Project\n\nVisit [docs](https://old.example.com/docs) for help.\n")

        links = [
            make_broken_link(
                "README.md",
                3,
                "https://old.example.com/docs",
                404,
                suggested_fix="https://new.example.com/docs",
                fix_confidence=0.9,
            ),
        ]

        modified = apply_fixes(tmp_path, links)
        assert modified == ["README.md"]

        content = readme.read_text()
        assert "https://new.example.com/docs" in content
        assert "https://old.example.com/docs" not in content
