"""Tests for repo_scout.models."""

from __future__ import annotations

from datetime import datetime, timezone

from repo_scout.models import (
    DiscoverySource,
    RepositoryRecord,
    ScoutConfig,
    make_repo_record,
)


class TestDiscoverySource:
    """Tests for DiscoverySource enum."""

    def test_awesome_list_value(self) -> None:
        assert DiscoverySource.AWESOME_LIST.value == "awesome_list"

    def test_starred_repo_value(self) -> None:
        assert DiscoverySource.STARRED_REPO.value == "starred_repo"

    def test_llm_suggestion_value(self) -> None:
        assert DiscoverySource.LLM_SUGGESTION.value == "llm_suggestion"

    def test_stargazer_target_value(self) -> None:
        assert DiscoverySource.STARGAZER_TARGET.value == "stargazer_target"

    def test_all_sources(self) -> None:
        assert len(DiscoverySource) == 4


class TestRepositoryRecord:
    """Tests for RepositoryRecord TypedDict."""

    def test_create_minimal(self) -> None:
        record: RepositoryRecord = {
            "owner": "octocat",
            "name": "hello-world",
            "full_name": "octocat/hello-world",
            "url": "https://github.com/octocat/hello-world",
            "description": None,
            "stars": None,
            "sources": ["awesome_list"],
            "discovered_at": "2024-01-01T00:00:00",
            "metadata": {},
        }
        assert record["owner"] == "octocat"
        assert record["description"] is None

    def test_create_full(self) -> None:
        record: RepositoryRecord = {
            "owner": "org",
            "name": "repo",
            "full_name": "org/repo",
            "url": "https://github.com/org/repo",
            "description": "A great repo",
            "stars": 1000,
            "sources": ["starred_repo", "awesome_list"],
            "discovered_at": "2024-01-01T00:00:00",
            "metadata": {"depth": 1},
        }
        assert record["stars"] == 1000
        assert len(record["sources"]) == 2


class TestScoutConfig:
    """Tests for ScoutConfig TypedDict."""

    def test_create_minimal(self) -> None:
        config: ScoutConfig = {}
        assert isinstance(config, dict)

    def test_create_full(self) -> None:
        config: ScoutConfig = {
            "github_token": "ghp_test",
            "llm_api_key": "sk-test",
            "max_star_depth": 3,
            "rate_limit_delay": 2.0,
            "output_path": "out.json",
            "output_format": "json",
        }
        assert config["max_star_depth"] == 3


class TestMakeRepoRecord:
    """Tests for make_repo_record factory."""

    def test_basic_creation(self) -> None:
        record = make_repo_record(
            owner="octocat",
            name="hello-world",
            source=DiscoverySource.AWESOME_LIST,
        )
        assert record["owner"] == "octocat"
        assert record["name"] == "hello-world"
        assert record["full_name"] == "octocat/hello-world"
        assert record["url"] == "https://github.com/octocat/hello-world"
        assert record["description"] is None
        assert record["stars"] is None
        assert record["sources"] == ["awesome_list"]
        assert record["metadata"] == {}

    def test_with_description_and_stars(self) -> None:
        record = make_repo_record(
            owner="org",
            name="repo",
            source=DiscoverySource.STARRED_REPO,
            description="My repo",
            stars=500,
        )
        assert record["description"] == "My repo"
        assert record["stars"] == 500
        assert record["sources"] == ["starred_repo"]

    def test_with_metadata(self) -> None:
        record = make_repo_record(
            owner="user",
            name="tool",
            source=DiscoverySource.LLM_SUGGESTION,
            metadata={"validated": True},
        )
        assert record["metadata"] == {"validated": True}
        assert record["sources"] == ["llm_suggestion"]

    def test_discovered_at_is_iso_format(self) -> None:
        record = make_repo_record(
            owner="a",
            name="b",
            source=DiscoverySource.AWESOME_LIST,
        )
        # Should parse as ISO 8601
        dt = datetime.fromisoformat(record["discovered_at"])
        assert dt.tzinfo == timezone.utc

    def test_none_metadata_defaults_to_empty_dict(self) -> None:
        record = make_repo_record(
            owner="a",
            name="b",
            source=DiscoverySource.AWESOME_LIST,
            metadata=None,
        )
        assert record["metadata"] == {}
