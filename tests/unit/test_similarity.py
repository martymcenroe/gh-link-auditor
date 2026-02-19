"""Unit tests for text similarity scoring (LLD #20, §10.0).

TDD: Tests written BEFORE implementation.
Covers: compute_similarity(), normalize_text()
"""

from gh_link_auditor.similarity import compute_similarity, normalize_text

# ---------------------------------------------------------------------------
# T170: Similarity score computation (REQ-10)
# ---------------------------------------------------------------------------


class TestComputeSimilarity:
    def test_identical_texts_return_one(self):
        """Identical texts produce similarity of 1.0."""
        assert compute_similarity("hello world", "hello world") == 1.0

    def test_completely_different_texts_return_low(self):
        """Totally different texts produce similarity near 0."""
        score = compute_similarity("abc def ghi", "xyz 123 456")
        assert score < 0.3

    def test_similar_texts_return_high(self):
        """Texts with minor differences score high."""
        a = "Installation Guide for Python"
        b = "Installation Guide for Python 3"
        score = compute_similarity(a, b)
        assert score >= 0.7

    def test_score_range_zero_to_one(self):
        """Score always between 0.0 and 1.0 inclusive."""
        score = compute_similarity("some text", "other text")
        assert 0.0 <= score <= 1.0

    def test_empty_strings_return_one(self):
        """Two empty strings are considered identical."""
        assert compute_similarity("", "") == 1.0

    def test_one_empty_string_returns_zero(self):
        """One empty string produces 0.0 similarity."""
        assert compute_similarity("hello", "") == 0.0
        assert compute_similarity("", "hello") == 0.0

    def test_case_insensitive_comparison(self):
        """Comparison is case-insensitive via normalization."""
        score = compute_similarity("Hello World", "hello world")
        assert score == 1.0

    def test_whitespace_normalized(self):
        """Extra whitespace doesn't affect similarity."""
        score = compute_similarity("hello  world", "hello world")
        assert score == 1.0

    def test_similarity_threshold_half(self):
        """Moderately similar texts cross 0.5 threshold."""
        a = "Getting Started with Flask Web Framework"
        b = "Getting Started with Django Web Framework"
        score = compute_similarity(a, b)
        assert score >= 0.5


# ---------------------------------------------------------------------------
# normalize_text
# ---------------------------------------------------------------------------


class TestNormalizeText:
    def test_lowercase(self):
        assert normalize_text("HELLO World") == "hello world"

    def test_strip_whitespace(self):
        assert normalize_text("  hello  ") == "hello"

    def test_collapse_internal_whitespace(self):
        assert normalize_text("hello   world") == "hello world"

    def test_strip_tabs_newlines(self):
        assert normalize_text("hello\t\nworld") == "hello world"

    def test_empty_string(self):
        assert normalize_text("") == ""
