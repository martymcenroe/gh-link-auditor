"""Tests for repo_scout.star_walker."""

from __future__ import annotations

from repo_scout.models import DiscoverySource, make_repo_record
from repo_scout.star_walker import get_user_starred, walk_starred_repos
from tests.fakes.github import FakeGitHubClient


def _make_starred(owner: str, name: str) -> dict:
    """Helper to create a starred repo record."""
    return make_repo_record(
        owner=owner,
        name=name,
        source=DiscoverySource.STARRED_REPO,
    )


class TestGetUserStarred:
    """Tests for get_user_starred."""

    def test_delegates_to_client(self) -> None:
        client = FakeGitHubClient()
        expected = [_make_starred("org", "repo")]
        client.configure_starred("user1", expected)

        result = get_user_starred("user1", client)
        assert result == expected
        assert client.get_starred_calls == ["user1"]


class TestWalkStarredRepos:
    """Tests for walk_starred_repos."""

    def test_single_depth(self) -> None:
        client = FakeGitHubClient()
        client.configure_starred(
            "root_user",
            [
                _make_starred("org1", "repo1"),
                _make_starred("org2", "repo2"),
            ],
        )

        result = walk_starred_repos("root_user", client, max_depth=1)
        assert len(result) == 2
        assert result[0]["metadata"]["root_user"] == "root_user"
        assert result[0]["metadata"]["depth"] == 0

    def test_cycle_detection(self) -> None:
        client = FakeGitHubClient()
        repos = [_make_starred("org", "repo1"), _make_starred("org", "repo2")]
        # Both root_user and org return the same repos
        client.configure_starred("root_user", repos)
        client.configure_starred("org", repos)

        result = walk_starred_repos("root_user", client, max_depth=2)
        # Only 2 unique repos, not 4
        assert len(result) == 2

    def test_max_depth_zero(self) -> None:
        client = FakeGitHubClient()
        result = walk_starred_repos("root_user", client, max_depth=0)
        assert result == []
        assert client.get_starred_calls == []

    def test_depth_two_traversal(self) -> None:
        client = FakeGitHubClient()
        client.configure_starred(
            "root_user",
            [
                _make_starred("org1", "repo1"),
                _make_starred("org2", "repo2"),
            ],
        )
        client.configure_starred("org1", [_make_starred("org3", "repo3")])
        client.configure_starred("org2", [_make_starred("org4", "repo4")])

        result = walk_starred_repos("root_user", client, max_depth=2)
        assert len(result) == 4
        # Depth 0 repos have depth=0
        assert result[0]["metadata"]["depth"] == 0
        assert result[1]["metadata"]["depth"] == 0
        # Depth 1 repos have depth=1
        assert result[2]["metadata"]["depth"] == 1
        assert result[3]["metadata"]["depth"] == 1

    def test_root_user_excluded_from_next_depth(self) -> None:
        client = FakeGitHubClient()
        # root_user starred a repo owned by root_user themselves
        client.configure_starred("root_user", [_make_starred("root_user", "my-repo")])

        result = walk_starred_repos("root_user", client, max_depth=2)
        assert len(result) == 1
        # Only called once (for root_user at depth 0)
        assert len(client.get_starred_calls) == 1

    def test_visited_parameter_pre_seeds(self) -> None:
        client = FakeGitHubClient()
        client.configure_starred(
            "root_user",
            [
                _make_starred("org", "already-seen"),
                _make_starred("org", "new-repo"),
            ],
        )

        visited = {"org/already-seen"}
        result = walk_starred_repos("root_user", client, max_depth=1, visited=visited)
        assert len(result) == 1
        assert result[0]["name"] == "new-repo"

    def test_empty_starred(self) -> None:
        client = FakeGitHubClient()
        # No starred repos configured → returns empty

        result = walk_starred_repos("root_user", client, max_depth=2)
        assert result == []
