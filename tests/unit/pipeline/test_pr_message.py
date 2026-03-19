"""Tests for pipeline PR message generation.

See Issue #85 for specification.
"""

from __future__ import annotations

from gh_link_auditor.pipeline.pr_message import (
    _build_verification_detail,
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
    """Tests for generate_pr_title_from_fixes()."""

    def test_empty_list(self) -> None:
        assert generate_pr_title_from_fixes([]) == "docs: fix broken links"

    def test_single_fix(self) -> None:
        title = generate_pr_title_from_fixes([_make_fix()])
        assert title == "docs: fix broken link in README.md"

    def test_multiple_fixes_same_file(self) -> None:
        fixes = [
            _make_fix(original_url="https://a.com"),
            _make_fix(original_url="https://b.com"),
        ]
        title = generate_pr_title_from_fixes(fixes)
        assert "2 broken links" in title
        assert "README.md" in title

    def test_multiple_files(self) -> None:
        fixes = [
            _make_fix(source_file="a.md"),
            _make_fix(source_file="b.md"),
        ]
        title = generate_pr_title_from_fixes(fixes)
        assert "2 broken links" in title
        assert "a.md" not in title  # Multiple files, no specific name

    def test_starts_with_docs_prefix(self) -> None:
        title = generate_pr_title_from_fixes([_make_fix()])
        assert title.startswith("docs:")


class TestBuildVerificationDetail:
    """Tests for _build_verification_detail()."""

    def test_redirect_source(self) -> None:
        verdict = _make_verdict(source="redirect")
        detail = _build_verification_detail(verdict)
        assert "redirects" in detail

    def test_archive_source(self) -> None:
        verdict = _make_verdict(source="archive")
        detail = _build_verification_detail(verdict)
        assert "archive.org" in detail

    def test_search_source(self) -> None:
        verdict = _make_verdict(source="search")
        detail = _build_verification_detail(verdict)
        assert "search" in detail

    def test_unknown_source(self) -> None:
        verdict = _make_verdict(source="unknown")
        detail = _build_verification_detail(verdict)
        assert "Verified" in detail

    def test_none_verdict(self) -> None:
        detail = _build_verification_detail(None)
        assert "Verified" in detail

    def test_no_candidate(self) -> None:
        verdict = Verdict(
            dead_link=DeadLink(
                url="https://old.com",
                source_file="a.md",
                line_number=1,
                link_text="t",
                http_status=404,
                error_type="http_error",
            ),
            candidate=None,
            confidence=0.0,
            reasoning="no match",
            approved=True,
        )
        detail = _build_verification_detail(verdict)
        assert "Verified" in detail


class TestFindVerdictForFix:
    """Tests for _find_verdict_for_fix()."""

    def test_finds_matching_verdict(self) -> None:
        fix = _make_fix()
        verdict = _make_verdict()
        result = _find_verdict_for_fix(fix, [verdict])
        assert result is verdict

    def test_returns_none_when_no_match(self) -> None:
        fix = _make_fix(original_url="https://different.com")
        verdict = _make_verdict()
        result = _find_verdict_for_fix(fix, [verdict])
        assert result is None

    def test_matches_on_both_url_and_file(self) -> None:
        fix = _make_fix(source_file="other.md")
        verdict = _make_verdict(source_file="README.md")
        result = _find_verdict_for_fix(fix, [verdict])
        assert result is None

    def test_empty_verdicts(self) -> None:
        fix = _make_fix()
        result = _find_verdict_for_fix(fix, [])
        assert result is None


class TestGeneratePrBodyFromFixes:
    """Tests for generate_pr_body_from_fixes()."""

    def test_single_fix_with_verdict(self) -> None:
        fix = _make_fix()
        verdict = _make_verdict()
        body = generate_pr_body_from_fixes([fix], [verdict])
        assert "I ran a link checker" in body
        assert "https://old.example.com/page" in body
        assert "https://new.example.com/page" in body
        assert "404" in body
        assert "line 5" in body

    def test_single_fix_without_verdict(self) -> None:
        fix = _make_fix()
        body = generate_pr_body_from_fixes([fix])
        assert "I ran a link checker" in body
        assert "https://old.example.com/page" in body
        assert "https://new.example.com/page" in body

    def test_multiple_fixes(self) -> None:
        fixes = [
            _make_fix(source_file="a.md", original_url="https://a.com", replacement_url="https://a-new.com"),
            _make_fix(source_file="b.md", original_url="https://b.com", replacement_url="https://b-new.com"),
        ]
        verdicts = [
            _make_verdict(source_file="a.md", original_url="https://a.com", replacement_url="https://a-new.com"),
            _make_verdict(source_file="b.md", original_url="https://b.com", replacement_url="https://b-new.com"),
        ]
        body = generate_pr_body_from_fixes(fixes, verdicts)
        assert "2 broken links" in body
        assert "https://a.com" in body
        assert "https://b.com" in body
        assert "https://a-new.com" in body
        assert "https://b-new.com" in body

    def test_empty_fixes(self) -> None:
        body = generate_pr_body_from_fixes([])
        assert "no fixes to apply" in body

    def test_no_bot_attribution(self) -> None:
        fix = _make_fix()
        body = generate_pr_body_from_fixes([fix])
        assert "Bot" not in body
        assert "bot" not in body
        assert "automated scanning" not in body
        assert "opt out" not in body

    def test_redirect_verification_detail(self) -> None:
        fix = _make_fix()
        verdict = _make_verdict(source="redirect")
        body = generate_pr_body_from_fixes([fix], [verdict])
        assert "redirects" in body

    def test_archive_verification_detail(self) -> None:
        fix = _make_fix()
        verdict = _make_verdict(source="archive")
        body = generate_pr_body_from_fixes([fix], [verdict])
        assert "archive.org" in body

    def test_includes_status_code(self) -> None:
        fix = _make_fix()
        verdict = _make_verdict(http_status=410)
        body = generate_pr_body_from_fixes([fix], [verdict])
        assert "410" in body

    def test_multiple_fixes_show_file_locations(self) -> None:
        fixes = [
            _make_fix(source_file="docs/guide.md", original_url="https://a.com", replacement_url="https://a-new.com"),
            _make_fix(source_file="docs/api.md", original_url="https://b.com", replacement_url="https://b-new.com"),
        ]
        verdicts = [
            _make_verdict(source_file="docs/guide.md", original_url="https://a.com", line_number=42),
            _make_verdict(source_file="docs/api.md", original_url="https://b.com", line_number=10),
        ]
        body = generate_pr_body_from_fixes(fixes, verdicts)
        assert "`docs/guide.md`" in body
        assert "`docs/api.md`" in body
