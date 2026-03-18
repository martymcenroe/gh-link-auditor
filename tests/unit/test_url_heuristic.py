"""Unit tests for URL pattern heuristic (LLD #20, §10.0).

TDD: Tests written BEFORE implementation.
Covers: URLHeuristic.slugify(), generate_candidates(), probe_candidates(),
        _generate_version_variants()
"""

from unittest.mock import patch

from gh_link_auditor.url_heuristic import URLHeuristic

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_heuristic() -> URLHeuristic:
    """Build a URLHeuristic with default config."""
    return URLHeuristic()


# ---------------------------------------------------------------------------
# T070: URL heuristic slugification (REQ-5)
# ---------------------------------------------------------------------------


class TestSlugify:
    def test_basic_title(self):
        h = _make_heuristic()
        assert h.slugify("Installation Guide") == "installation-guide"

    def test_special_characters_removed(self):
        h = _make_heuristic()
        assert h.slugify("What's New in v2.0?") == "whats-new-in-v20"

    def test_multiple_spaces_collapsed(self):
        h = _make_heuristic()
        assert h.slugify("hello   world") == "hello-world"

    def test_leading_trailing_dashes_stripped(self):
        h = _make_heuristic()
        result = h.slugify("  Hello World  ")
        assert not result.startswith("-")
        assert not result.endswith("-")

    def test_empty_string(self):
        h = _make_heuristic()
        assert h.slugify("") == ""

    def test_unicode_handled(self):
        h = _make_heuristic()
        result = h.slugify("Café Guide")
        assert isinstance(result, str)
        assert " " not in result


# ---------------------------------------------------------------------------
# T070: generate_candidates (REQ-5)
# ---------------------------------------------------------------------------


class TestGenerateCandidates:
    def test_returns_list_of_urls(self):
        h = _make_heuristic()
        candidates = h.generate_candidates("example.com", "Installation Guide", "/docs/install")
        assert isinstance(candidates, list)
        assert len(candidates) > 0
        assert all(isinstance(c, str) for c in candidates)

    def test_candidates_include_slugified_title(self):
        h = _make_heuristic()
        candidates = h.generate_candidates("example.com", "Installation Guide", "/docs/install")
        assert any("installation-guide" in c for c in candidates)

    def test_candidates_use_https(self):
        h = _make_heuristic()
        candidates = h.generate_candidates("example.com", "Getting Started", "/docs/start")
        assert all(c.startswith("https://") for c in candidates)

    def test_candidates_include_domain(self):
        h = _make_heuristic()
        candidates = h.generate_candidates("docs.python.org", "Tutorial", "/tutorial/")
        assert all("docs.python.org" in c for c in candidates)

    def test_path_prefix_variants(self):
        """Candidates try various path prefixes like /docs/, /guide/ etc."""
        h = _make_heuristic()
        candidates = h.generate_candidates("example.com", "Setup Guide", "/old-path")
        paths = [c.split("example.com")[1] for c in candidates]
        # Should include at least the slug under different prefixes
        assert len(paths) >= 2


# ---------------------------------------------------------------------------
# T080: probe_candidates max three (REQ-5)
# ---------------------------------------------------------------------------


class TestProbeCandidates:
    def test_max_three_results(self):
        """Only up to 3 live candidates returned."""
        h = _make_heuristic()
        candidates = [
            "https://example.com/a",
            "https://example.com/b",
            "https://example.com/c",
            "https://example.com/d",
            "https://example.com/e",
        ]
        # Mock all as live (200)
        with patch(
            "gh_link_auditor.url_heuristic.check_url",
            return_value={"status": "ok", "status_code": 200},
        ):
            live = h.probe_candidates(candidates, max_results=3)
        assert len(live) <= 3

    def test_only_live_urls_returned(self):
        """Only URLs returning 2xx are included."""
        h = _make_heuristic()
        candidates = ["https://example.com/good", "https://example.com/bad"]

        def _mock_check(url, **kwargs):
            if "good" in url:
                return {"status": "ok", "status_code": 200}
            return {"status": "error", "status_code": 404}

        with patch("gh_link_auditor.url_heuristic.check_url", side_effect=_mock_check):
            live = h.probe_candidates(candidates)
        assert live == ["https://example.com/good"]

    def test_empty_candidates_returns_empty(self):
        h = _make_heuristic()
        assert h.probe_candidates([]) == []


# ---------------------------------------------------------------------------
# Version variants
# ---------------------------------------------------------------------------


class TestVersionVariants:
    def test_v1_generates_v2_v3(self):
        h = _make_heuristic()
        variants = h._generate_version_variants("/docs/v1/install")
        assert "/docs/v2/install" in variants
        assert "/docs/v3/install" in variants

    def test_generates_latest_variant(self):
        h = _make_heuristic()
        variants = h._generate_version_variants("/docs/v1/install")
        assert "/docs/latest/install" in variants

    def test_no_version_returns_empty(self):
        h = _make_heuristic()
        variants = h._generate_version_variants("/docs/install")
        assert variants == []


# ---------------------------------------------------------------------------
# Coverage gap tests
# ---------------------------------------------------------------------------


class TestGenerateCandidatesCoverageGaps:
    def test_empty_slug_returns_empty_list(self):
        """Title that produces empty slug returns no candidates (line 61)."""
        h = _make_heuristic()
        candidates = h.generate_candidates("example.com", "!!!", "/docs/old")
        assert candidates == []

    def test_version_variants_included_in_candidates(self):
        """Path with version number includes version variants (line 83)."""
        h = _make_heuristic()
        candidates = h.generate_candidates("example.com", "Install Guide", "/docs/v1/install")
        assert any("/docs/v2/install" in c for c in candidates)
        assert any("/docs/latest/install" in c for c in candidates)
