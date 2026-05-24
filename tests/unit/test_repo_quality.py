"""Tests for repo quality assessment and contributing guidelines.

See Issues #98, #99 for specification.
"""

from __future__ import annotations

from unittest.mock import patch

from gh_link_auditor.repo_quality import (
    RepoQuality,
    analyze_contributing_guidelines,
    fetch_contributing_guidelines,
    fetch_repo_metadata,
    format_quality_summary,
)


class _MockCompleted:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class TestFetchRepoMetadata:
    """Tests for fetch_repo_metadata()."""

    def test_fetches_stars_and_pushed_at(self) -> None:
        # #316: jq now also surfaces archived / disabled / license. The legacy
        # stars + pushed_at fields still populate the same way; pre-existing
        # keys are unchanged.
        repo_data = _MockCompleted(
            '{"stars": 15000, "pushed_at": "2026-03-01T12:00:00Z", '
            '"archived": false, "disabled": false, "license": "BSD-3-Clause"}'
        )
        contrib_data = _MockCompleted("30")

        with patch("subprocess.run", side_effect=[repo_data, contrib_data]):
            quality = fetch_repo_metadata("encode", "httpx")

        assert quality.stars == 15000
        assert quality.pushed_at == "2026-03-01T12:00:00Z"
        assert quality.contributors == 30

    def test_handles_api_failure(self) -> None:
        failed = _MockCompleted("", returncode=1)

        with patch("subprocess.run", return_value=failed):
            quality = fetch_repo_metadata("org", "repo")

        assert quality.stars == 0
        assert quality.contributors == 0

    def test_handles_gh_not_found(self) -> None:
        with patch("subprocess.run", side_effect=FileNotFoundError):
            quality = fetch_repo_metadata("org", "repo")

        assert quality.stars == 0


class TestFetchRepoMetadataExtended:
    """#316: archived / disabled / license fields surfaced by the extended jq query."""

    def test_archived_repo_surfaces_true(self) -> None:
        repo_data = _MockCompleted(
            '{"stars": 100, "pushed_at": "2024-01-01T00:00:00Z", "archived": true, "disabled": false, "license": "MIT"}'
        )
        contrib_data = _MockCompleted("3")

        with patch("subprocess.run", side_effect=[repo_data, contrib_data]):
            quality = fetch_repo_metadata("org", "repo")

        assert quality.archived is True
        assert quality.disabled is False

    def test_disabled_repo_surfaces_true(self) -> None:
        repo_data = _MockCompleted(
            '{"stars": 5, "pushed_at": "2024-01-01T00:00:00Z", "archived": false, "disabled": true, "license": null}'
        )
        contrib_data = _MockCompleted("1")

        with patch("subprocess.run", side_effect=[repo_data, contrib_data]):
            quality = fetch_repo_metadata("org", "repo")

        assert quality.disabled is True
        assert quality.archived is False
        assert quality.license is None

    def test_license_spdx_is_captured(self) -> None:
        repo_data = _MockCompleted(
            '{"stars": 200, "pushed_at": "2026-04-01T00:00:00Z", '
            '"archived": false, "disabled": false, "license": "Apache-2.0"}'
        )
        contrib_data = _MockCompleted("10")

        with patch("subprocess.run", side_effect=[repo_data, contrib_data]):
            quality = fetch_repo_metadata("org", "repo")

        assert quality.license == "Apache-2.0"

    def test_missing_license_returns_none(self) -> None:
        repo_data = _MockCompleted(
            '{"stars": 3, "pushed_at": "2026-01-01T00:00:00Z", "archived": false, "disabled": false, "license": null}'
        )
        contrib_data = _MockCompleted("1")

        with patch("subprocess.run", side_effect=[repo_data, contrib_data]):
            quality = fetch_repo_metadata("org", "repo")

        assert quality.license is None

    def test_default_archived_disabled_when_keys_missing(self) -> None:
        # Backward compat: if older jq output (or a partial response) omits the
        # new fields, defaults are False / None — never raises.
        repo_data = _MockCompleted('{"stars": 50, "pushed_at": "2025-12-01T00:00:00Z"}')
        contrib_data = _MockCompleted("5")

        with patch("subprocess.run", side_effect=[repo_data, contrib_data]):
            quality = fetch_repo_metadata("org", "repo")

        assert quality.archived is False
        assert quality.disabled is False
        assert quality.license is None


class TestFetchContributingGuidelines:
    """Tests for fetch_contributing_guidelines()."""

    def test_finds_root_contributing(self) -> None:
        import base64

        content = base64.b64encode(b"# Contributing\nPlease open a discussion first.").decode()

        def fake_run(cmd, **kwargs):
            if "CONTRIBUTING.md" in str(cmd) and ".github" not in str(cmd):
                return _MockCompleted(content)
            return _MockCompleted("", returncode=1)

        with patch("subprocess.run", side_effect=fake_run):
            text = fetch_contributing_guidelines("org", "repo")

        assert "Contributing" in text
        assert "discussion" in text

    def test_finds_github_contributing(self) -> None:
        import base64

        content = base64.b64encode(b"# Contributing to HTTPX").decode()

        def fake_run(cmd, **kwargs):
            if ".github/CONTRIBUTING.md" in str(cmd):
                return _MockCompleted(content)
            return _MockCompleted("", returncode=1)

        with patch("subprocess.run", side_effect=fake_run):
            text = fetch_contributing_guidelines("org", "repo")

        assert "HTTPX" in text

    def test_returns_empty_when_not_found(self) -> None:
        with patch("subprocess.run", return_value=_MockCompleted("", returncode=1)):
            text = fetch_contributing_guidelines("org", "repo")

        assert text == ""


class TestAnalyzeContributingGuidelines:
    """Tests for analyze_contributing_guidelines()."""

    def test_detects_discussion_first(self) -> None:
        text = "Contributions should generally start out with a discussion."
        warnings = analyze_contributing_guidelines(text)
        assert any("discussion" in w.lower() for w in warnings)

    def test_detects_discussion_before(self) -> None:
        text = "Please open a discussion before submitting a pull request."
        warnings = analyze_contributing_guidelines(text)
        assert any("discussion" in w.lower() for w in warnings)

    def test_detects_no_bots(self) -> None:
        text = "No bot or automated contributions accepted."
        warnings = analyze_contributing_guidelines(text)
        assert any("automated" in w.lower() for w in warnings)

    def test_detects_cla(self) -> None:
        text = "You must sign a Contributor License Agreement before contributing."
        warnings = analyze_contributing_guidelines(text)
        assert any("CLA" in w for w in warnings)

    def test_no_warnings_for_clean_contributing(self) -> None:
        text = "We welcome contributions! Fork the repo and submit a PR."
        warnings = analyze_contributing_guidelines(text)
        assert warnings == []

    def test_empty_text_returns_empty(self) -> None:
        assert analyze_contributing_guidelines("") == []

    def test_no_duplicate_warnings(self) -> None:
        text = "Please start with a discussion. Start as a discussion before PRs."
        warnings = analyze_contributing_guidelines(text)
        discussion_warnings = [w for w in warnings if "discussion" in w.lower()]
        assert len(discussion_warnings) == 1


class TestFormatQualitySummary:
    """Tests for format_quality_summary()."""

    def test_full_summary(self) -> None:
        quality = RepoQuality(stars=15000, pushed_at="2026-03-01T12:00:00Z", contributors=247)
        summary = format_quality_summary(quality)
        assert "15,000 stars" in summary
        assert "247 contributors" in summary
        assert "2026-03-01" in summary

    def test_partial_data(self) -> None:
        quality = RepoQuality(stars=500)
        summary = format_quality_summary(quality)
        assert "500 stars" in summary

    def test_no_data(self) -> None:
        quality = RepoQuality()
        summary = format_quality_summary(quality)
        assert "no metadata" in summary
