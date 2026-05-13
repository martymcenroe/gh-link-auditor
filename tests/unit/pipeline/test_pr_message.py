"""Tests for casual-register PR message generation.

See Issue #209 (current spec) and Issue #85 (original spec, now replaced).
"""

from __future__ import annotations

import pytest

from gh_link_auditor.pipeline.pr_message import (
    _find_verdict_for_fix,
    generate_pr_body_from_fixes,
    generate_pr_title_from_fixes,
)
from gh_link_auditor.pipeline.state import (
    DeadLink,
    FixPatch,
    ReplacementCandidate,
    Verdict,
)

FORBIDDEN_AI_TELLS = (
    "docs:",
    "I ran",
    "**",
    "—",  # em-dash
    "→",  # rightwards arrow
    "Verified",
    "automated",
)


def _make_fix(
    source_file: str = "README.md",
    original_url: str = "https://old.example.com/page",
    replacement_url: str = "https://new.example.com/page",
) -> FixPatch:
    return FixPatch(
        source_file=source_file,
        original_url=original_url,
        replacement_url=replacement_url,
        unified_diff="--- a/README.md\n+++ b/README.md\n",
    )


def _make_verdict(
    original_url: str = "https://old.example.com/page",
    replacement_url: str = "https://new.example.com/page",
    source_file: str = "README.md",
    http_status: int = 404,
    line_number: int = 5,
    source: str = "redirect",
) -> Verdict:
    dl = DeadLink(
        url=original_url,
        source_file=source_file,
        line_number=line_number,
        link_text="link",
        http_status=http_status,
        error_type="http_error",
    )
    candidate = ReplacementCandidate(
        url=replacement_url,
        source=source,
        title=None,
        snippet=None,
    )
    return Verdict(
        dead_link=dl,
        candidate=candidate,
        confidence=0.95,
        reasoning="good match",
        approved=True,
    )


class TestGeneratePrTitleFromFixes:
    def test_empty_list(self) -> None:
        assert generate_pr_title_from_fixes([]) == "fix broken docs links"

    def test_single_fix(self) -> None:
        assert generate_pr_title_from_fixes([_make_fix()]) == "fix broken docs link"

    def test_multiple_fixes(self) -> None:
        fixes = [_make_fix(original_url="https://a.com"), _make_fix(original_url="https://b.com")]
        assert generate_pr_title_from_fixes(fixes) == "fix 2 broken docs links"

    def test_no_conventional_prefix(self) -> None:
        for fixes in ([], [_make_fix()], [_make_fix(), _make_fix(original_url="https://b.com")]):
            assert not generate_pr_title_from_fixes(fixes).startswith("docs:")
            assert not generate_pr_title_from_fixes(fixes).startswith("feat:")
            assert not generate_pr_title_from_fixes(fixes).startswith("chore:")

    def test_lowercase_only(self) -> None:
        for fixes in ([], [_make_fix()], [_make_fix(), _make_fix(original_url="https://b.com")]):
            title = generate_pr_title_from_fixes(fixes)
            assert title == title.lower()

    def test_no_period(self) -> None:
        for fixes in ([], [_make_fix()], [_make_fix(), _make_fix(original_url="https://b.com")]):
            assert not generate_pr_title_from_fixes(fixes).endswith(".")

    def test_no_file_name_in_title(self) -> None:
        """File name is in the body/diff, not the title."""
        assert "README.md" not in generate_pr_title_from_fixes([_make_fix()])


class TestFindVerdictForFix:
    def test_finds_matching_verdict(self) -> None:
        fix = _make_fix()
        verdict = _make_verdict()
        assert _find_verdict_for_fix(fix, [verdict]) is verdict

    def test_returns_none_when_no_url_match(self) -> None:
        fix = _make_fix(original_url="https://different.com")
        assert _find_verdict_for_fix(fix, [_make_verdict()]) is None

    def test_returns_none_when_no_file_match(self) -> None:
        fix = _make_fix(source_file="other.md")
        verdict = _make_verdict(source_file="README.md")
        assert _find_verdict_for_fix(fix, [verdict]) is None

    def test_empty_verdicts(self) -> None:
        assert _find_verdict_for_fix(_make_fix(), []) is None


class TestGeneratePrBodyFromFixes:
    def test_single_fix_exact_format(self) -> None:
        fix = _make_fix()
        body = generate_pr_body_from_fixes([fix], [_make_verdict()])
        assert body == (
            "https://old.example.com/page is dead\n\nthink this is the one you want: https://new.example.com/page"
        )

    def test_single_fix_without_verdict(self) -> None:
        body = generate_pr_body_from_fixes([_make_fix()])
        assert "https://old.example.com/page is dead" in body
        assert "think this is the one you want: https://new.example.com/page" in body

    def test_single_fix_no_status_code(self) -> None:
        """HTTP status not in body — it's noise; maintainer can curl."""
        body = generate_pr_body_from_fixes([_make_fix()], [_make_verdict(http_status=404)])
        assert "404" not in body

    def test_single_fix_no_line_number(self) -> None:
        """Line number not in single-fix body — it's in the diff."""
        body = generate_pr_body_from_fixes([_make_fix()], [_make_verdict(line_number=42)])
        assert "line 42" not in body
        assert "line 5" not in body

    def test_multiple_fixes_header(self) -> None:
        fixes = [
            _make_fix(source_file="a.md", original_url="https://a.com"),
            _make_fix(source_file="b.md", original_url="https://b.com"),
        ]
        body = generate_pr_body_from_fixes(fixes)
        assert body.startswith("found 2 dead links in the docs")

    def test_multiple_fixes_arrows_are_ascii(self) -> None:
        fixes = [
            _make_fix(source_file="a.md", original_url="https://a.com", replacement_url="https://a-new.com"),
            _make_fix(source_file="b.md", original_url="https://b.com", replacement_url="https://b-new.com"),
        ]
        body = generate_pr_body_from_fixes(fixes)
        assert "->" in body
        assert "→" not in body

    def test_multiple_fixes_with_line_numbers(self) -> None:
        fixes = [
            _make_fix(source_file="docs/guide.md", original_url="https://a.com", replacement_url="https://a-new.com"),
            _make_fix(source_file="docs/api.md", original_url="https://b.com", replacement_url="https://b-new.com"),
        ]
        verdicts = [
            _make_verdict(source_file="docs/guide.md", original_url="https://a.com", line_number=42),
            _make_verdict(source_file="docs/api.md", original_url="https://b.com", line_number=10),
        ]
        body = generate_pr_body_from_fixes(fixes, verdicts)
        assert "docs/guide.md line 42:" in body
        assert "docs/api.md line 10:" in body

    def test_multiple_fixes_without_verdicts_omit_line_number(self) -> None:
        fixes = [
            _make_fix(source_file="a.md", original_url="https://a.com"),
            _make_fix(source_file="b.md", original_url="https://b.com"),
        ]
        body = generate_pr_body_from_fixes(fixes)
        assert "a.md: https://a.com" in body
        assert "b.md: https://b.com" in body
        assert "line" not in body

    def test_empty_fixes(self) -> None:
        assert generate_pr_body_from_fixes([]) == "ran a check but found nothing worth fixing"

    @pytest.mark.parametrize("tell", FORBIDDEN_AI_TELLS)
    def test_single_fix_no_ai_tells(self, tell: str) -> None:
        body = generate_pr_body_from_fixes([_make_fix()], [_make_verdict()])
        assert tell not in body, f"AI-tell {tell!r} leaked into single-fix body"

    @pytest.mark.parametrize("tell", FORBIDDEN_AI_TELLS)
    def test_multiple_fixes_no_ai_tells(self, tell: str) -> None:
        fixes = [
            _make_fix(source_file="a.md", original_url="https://a.com"),
            _make_fix(source_file="b.md", original_url="https://b.com"),
        ]
        verdicts = [
            _make_verdict(source_file="a.md", original_url="https://a.com"),
            _make_verdict(source_file="b.md", original_url="https://b.com"),
        ]
        body = generate_pr_body_from_fixes(fixes, verdicts)
        assert tell not in body, f"AI-tell {tell!r} leaked into multi-fix body"

    @pytest.mark.parametrize("tell", FORBIDDEN_AI_TELLS)
    def test_empty_no_ai_tells(self, tell: str) -> None:
        body = generate_pr_body_from_fixes([])
        assert tell not in body

    def test_body_is_lowercase_apart_from_urls(self) -> None:
        """Body prose is lowercase. URLs may contain mixed case."""
        body = generate_pr_body_from_fixes([_make_fix(original_url="https://Example.com/Page")])
        prose = body.replace("https://Example.com/Page", "").replace("https://new.example.com/page", "")
        for ch in prose:
            if ch.isalpha():
                assert ch.islower(), f"non-URL char {ch!r} not lowercase"

    def test_no_bold_markdown(self) -> None:
        body = generate_pr_body_from_fixes([_make_fix()], [_make_verdict()])
        assert "**" not in body

    def test_no_backticks(self) -> None:
        """Backticked file paths look formatted/bot-like in casual register."""
        fixes = [
            _make_fix(source_file="docs/guide.md", original_url="https://a.com"),
            _make_fix(source_file="docs/api.md", original_url="https://b.com"),
        ]
        body = generate_pr_body_from_fixes(fixes)
        assert "`" not in body

    def test_no_bot_words(self) -> None:
        body = generate_pr_body_from_fixes([_make_fix()], [_make_verdict()])
        lowered = body.lower()
        assert "bot" not in lowered
        assert "automated scanning" not in lowered
        assert "opt out" not in lowered
