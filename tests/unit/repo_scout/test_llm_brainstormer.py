"""Tests for repo_scout.llm_brainstormer."""

from __future__ import annotations

from unittest.mock import MagicMock

from repo_scout.llm_brainstormer import (
    build_suggestion_prompt,
    parse_llm_response,
    suggest_repos,
    validate_suggestions,
)


class TestBuildSuggestionPrompt:
    """Tests for build_suggestion_prompt."""

    def test_basic_prompt(self) -> None:
        prompt = build_suggestion_prompt(
            keywords=["python", "testing"],
            existing_repos=["org/repo1"],
        )
        assert "python, testing" in prompt
        assert "org/repo1" in prompt

    def test_empty_keywords(self) -> None:
        prompt = build_suggestion_prompt(keywords=[], existing_repos=[])
        assert "owner/repo" in prompt.lower() or "repositories" in prompt.lower()

    def test_truncates_existing_repos(self) -> None:
        existing = [f"org/repo{i}" for i in range(30)]
        prompt = build_suggestion_prompt(keywords=["test"], existing_repos=existing)
        # Only first 20 should appear
        assert "org/repo19" in prompt
        assert "org/repo20" not in prompt


class TestParseLlmResponse:
    """Tests for parse_llm_response."""

    def test_simple_list(self) -> None:
        response = """Here are some repos:
- owner/repo1
- org/repo2
- user/tool
"""
        result = parse_llm_response(response)
        assert result == ["owner/repo1", "org/repo2", "user/tool"]

    def test_inline_format(self) -> None:
        response = "Try owner/repo1 and org/repo2 for that."
        result = parse_llm_response(response)
        assert "owner/repo1" in result
        assert "org/repo2" in result

    def test_dedup(self) -> None:
        response = "owner/repo1 and also owner/repo1 again."
        result = parse_llm_response(response)
        assert result == ["owner/repo1"]

    def test_empty_response(self) -> None:
        result = parse_llm_response("")
        assert result == []

    def test_no_matches(self) -> None:
        result = parse_llm_response("No repos here, just plain text.")
        assert result == []

    def test_special_chars_in_names(self) -> None:
        response = "Check out my-org/my_repo.js for details."
        result = parse_llm_response(response)
        assert "my-org/my_repo.js" in result

    def test_preserves_order(self) -> None:
        response = "z-org/z-repo then a-org/a-repo"
        result = parse_llm_response(response)
        assert result[0] == "z-org/z-repo"
        assert result[1] == "a-org/a-repo"


class TestValidateSuggestions:
    """Tests for validate_suggestions."""

    def test_valid_repos(self) -> None:
        mock_client = MagicMock()
        mock_client.repo_exists.return_value = True

        records = validate_suggestions(["org/repo1", "org/repo2"], mock_client)
        assert len(records) == 2
        assert records[0]["full_name"] == "org/repo1"
        assert records[0]["sources"] == ["llm_suggestion"]

    def test_invalid_repo_skipped(self) -> None:
        mock_client = MagicMock()
        mock_client.repo_exists.side_effect = [True, False]

        records = validate_suggestions(["org/real", "org/fake"], mock_client)
        assert len(records) == 1
        assert records[0]["full_name"] == "org/real"

    def test_bad_format_skipped(self) -> None:
        mock_client = MagicMock()
        records = validate_suggestions(["not-a-repo-format"], mock_client)
        assert records == []
        mock_client.repo_exists.assert_not_called()

    def test_empty_list(self) -> None:
        mock_client = MagicMock()
        records = validate_suggestions([], mock_client)
        assert records == []


class TestSuggestRepos:
    """Tests for suggest_repos."""

    def test_no_llm_response_returns_empty(self) -> None:
        result = suggest_repos(
            keywords=["python"],
            existing_repos=[],
            llm_response=None,
        )
        assert result == []

    def test_with_response_no_client(self) -> None:
        result = suggest_repos(
            keywords=["python"],
            existing_repos=[],
            llm_response="Try org/repo1 and org/repo2",
            github_client=None,
        )
        assert len(result) == 2
        assert result[0]["full_name"] == "org/repo1"
        assert result[0]["metadata"]["validated"] is False

    def test_with_response_and_client(self) -> None:
        mock_client = MagicMock()
        mock_client.repo_exists.return_value = True

        result = suggest_repos(
            keywords=["python"],
            existing_repos=[],
            llm_response="org/repo1",
            github_client=mock_client,
        )
        assert len(result) == 1
        assert result[0]["full_name"] == "org/repo1"
        assert result[0]["metadata"]["suggestion"] == "org/repo1"

    def test_empty_response_text(self) -> None:
        result = suggest_repos(
            keywords=["python"],
            existing_repos=[],
            llm_response="No repos to suggest",
        )
        assert result == []

    def test_unvalidated_records_have_metadata(self) -> None:
        result = suggest_repos(
            keywords=["test"],
            existing_repos=[],
            llm_response="org/repo",
            github_client=None,
        )
        assert result[0]["metadata"]["suggestion"] == "org/repo"
        assert result[0]["metadata"]["validated"] is False
