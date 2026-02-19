"""Tests for repo_scout.aggregator."""

from __future__ import annotations

from repo_scout.aggregator import deduplicate_repos, merge_sources, sort_by_relevance
from repo_scout.models import DiscoverySource, RepositoryRecord, make_repo_record


def _repo(
    owner: str = "org",
    name: str = "repo",
    source: DiscoverySource = DiscoverySource.AWESOME_LIST,
    stars: int | None = None,
    description: str | None = None,
    metadata: dict | None = None,
) -> RepositoryRecord:
    return make_repo_record(
        owner=owner,
        name=name,
        source=source,
        stars=stars,
        description=description,
        metadata=metadata,
    )


class TestMergeSources:
    """Tests for merge_sources."""

    def test_combines_sources(self) -> None:
        existing = _repo(source=DiscoverySource.AWESOME_LIST)
        new = _repo(source=DiscoverySource.STARRED_REPO)
        merged = merge_sources(existing, new)
        assert set(merged["sources"]) == {"awesome_list", "starred_repo"}

    def test_keeps_highest_star_count(self) -> None:
        existing = _repo(stars=100)
        new = _repo(stars=500)
        merged = merge_sources(existing, new)
        assert merged["stars"] == 500

    def test_keeps_existing_stars_if_higher(self) -> None:
        existing = _repo(stars=500)
        new = _repo(stars=100)
        merged = merge_sources(existing, new)
        assert merged["stars"] == 500

    def test_new_stars_replace_none(self) -> None:
        existing = _repo(stars=None)
        new = _repo(stars=200)
        merged = merge_sources(existing, new)
        assert merged["stars"] == 200

    def test_keeps_none_if_both_none(self) -> None:
        existing = _repo(stars=None)
        new = _repo(stars=None)
        merged = merge_sources(existing, new)
        assert merged["stars"] is None

    def test_fills_missing_description(self) -> None:
        existing = _repo(description=None)
        new = _repo(description="My repo")
        merged = merge_sources(existing, new)
        assert merged["description"] == "My repo"

    def test_keeps_existing_description(self) -> None:
        existing = _repo(description="Original")
        new = _repo(description="New")
        merged = merge_sources(existing, new)
        assert merged["description"] == "Original"

    def test_merges_metadata(self) -> None:
        existing = _repo(metadata={"key1": "val1"})
        new = _repo(metadata={"key2": "val2"})
        merged = merge_sources(existing, new)
        assert merged["metadata"] == {"key1": "val1", "key2": "val2"}

    def test_existing_metadata_takes_precedence(self) -> None:
        existing = _repo(metadata={"key": "old"})
        new = _repo(metadata={"key": "new"})
        merged = merge_sources(existing, new)
        assert merged["metadata"]["key"] == "old"

    def test_empty_metadata_merge(self) -> None:
        existing = _repo(metadata={})
        new = _repo(metadata={})
        merged = merge_sources(existing, new)
        assert merged["metadata"] == {}


class TestDeduplicateRepos:
    """Tests for deduplicate_repos."""

    def test_no_duplicates(self) -> None:
        repos = [_repo(name="a"), _repo(name="b"), _repo(name="c")]
        result = deduplicate_repos(repos)
        assert len(result) == 3

    def test_removes_duplicates(self) -> None:
        repos = [
            _repo(name="repo", source=DiscoverySource.AWESOME_LIST),
            _repo(name="repo", source=DiscoverySource.STARRED_REPO),
        ]
        result = deduplicate_repos(repos)
        assert len(result) == 1
        assert set(result[0]["sources"]) == {"awesome_list", "starred_repo"}

    def test_case_insensitive(self) -> None:
        repos = [
            _repo(owner="Org", name="Repo"),
            _repo(owner="org", name="repo"),
        ]
        result = deduplicate_repos(repos)
        assert len(result) == 1

    def test_empty_list(self) -> None:
        result = deduplicate_repos([])
        assert result == []

    def test_preserves_order(self) -> None:
        repos = [_repo(name="z"), _repo(name="a")]
        result = deduplicate_repos(repos)
        assert result[0]["name"] == "z"
        assert result[1]["name"] == "a"


class TestSortByRelevance:
    """Tests for sort_by_relevance."""

    def test_sort_by_source_count(self) -> None:
        repo_one_source = _repo(name="one")
        repo_two_sources = _repo(name="two")
        repo_two_sources["sources"] = ["awesome_list", "starred_repo"]

        result = sort_by_relevance([repo_one_source, repo_two_sources])
        assert result[0]["name"] == "two"  # More sources first
        assert result[1]["name"] == "one"

    def test_sort_by_stars_when_same_sources(self) -> None:
        repo_low = _repo(name="low", stars=10)
        repo_high = _repo(name="high", stars=1000)

        result = sort_by_relevance([repo_low, repo_high])
        assert result[0]["name"] == "high"  # More stars first
        assert result[1]["name"] == "low"

    def test_none_stars_treated_as_zero(self) -> None:
        repo_none = _repo(name="none", stars=None)
        repo_some = _repo(name="some", stars=1)

        result = sort_by_relevance([repo_none, repo_some])
        assert result[0]["name"] == "some"

    def test_empty_list(self) -> None:
        result = sort_by_relevance([])
        assert result == []

    def test_single_item(self) -> None:
        repos = [_repo(name="only")]
        result = sort_by_relevance(repos)
        assert len(result) == 1
