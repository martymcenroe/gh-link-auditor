"""Repo Scout flow integration tests.

Tests multi-source aggregation and output compatibility with batch engine.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from repo_scout.aggregator import deduplicate_repos, sort_by_relevance
from repo_scout.models import DiscoverySource, make_repo_record
from repo_scout.output_writer import write_output


@pytest.mark.integration
class TestRepoScoutFlow:
    """Multi-source aggregation and output flow tests."""

    def test_multi_source_aggregation(self) -> None:
        """Awesome + Starred + Stargazer → deduplicated output."""
        awesome_repos = [
            make_repo_record("org", "tool-a", DiscoverySource.AWESOME_LIST),
            make_repo_record("org", "tool-b", DiscoverySource.AWESOME_LIST),
        ]
        starred_repos = [
            make_repo_record("org", "tool-b", DiscoverySource.STARRED_REPO, stars=50),
            make_repo_record("user", "tool-c", DiscoverySource.STARRED_REPO),
        ]
        stargazer_repos = [
            make_repo_record("alice", "tool-d", DiscoverySource.STARGAZER_TARGET),
        ]

        all_repos = awesome_repos + starred_repos + stargazer_repos
        deduped = deduplicate_repos(all_repos)
        sorted_repos = sort_by_relevance(deduped)

        # Should have 4 unique repos (tool-b merged)
        assert len(sorted_repos) == 4
        # tool-b should have both sources
        tool_b = next(r for r in sorted_repos if r["name"] == "tool-b")
        assert "awesome_list" in tool_b["sources"]
        assert "starred_repo" in tool_b["sources"]

    def test_output_loads_as_valid_json(self, tmp_path: Path) -> None:
        """write_output JSON → JSON.loads succeeds."""
        repos = [
            make_repo_record("org", "repo1", DiscoverySource.AWESOME_LIST, stars=100),
            make_repo_record("user", "repo2", DiscoverySource.STARRED_REPO),
        ]

        output_path = str(tmp_path / "targets.json")
        count = write_output(repos, output_path, fmt="json")
        assert count == 2

        # Verify the output is valid JSON that can be loaded
        data = json.loads(Path(output_path).read_text())
        assert len(data) == 2
        assert data[0]["full_name"] == "org/repo1"

    def test_duplicate_repos_across_sources_merged(self) -> None:
        """Same repo from 2 sources has merged source list."""
        repo1 = make_repo_record(
            "org",
            "shared-repo",
            DiscoverySource.AWESOME_LIST,
            description="From awesome list",
            stars=10,
        )
        repo2 = make_repo_record(
            "org",
            "shared-repo",
            DiscoverySource.STARRED_REPO,
            description=None,
            stars=50,
        )

        deduped = deduplicate_repos([repo1, repo2])
        assert len(deduped) == 1

        merged = deduped[0]
        assert "awesome_list" in merged["sources"]
        assert "starred_repo" in merged["sources"]
        # Stars should be highest
        assert merged["stars"] == 50
        # Description should be preserved from first source
        assert merged["description"] == "From awesome list"
