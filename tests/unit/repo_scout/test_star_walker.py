"""Tests for repo_scout.star_walker."""

from __future__ import annotations

from unittest.mock import MagicMock

from repo_scout.models import DiscoverySource, make_repo_record
from repo_scout.star_walker import get_user_starred, walk_starred_repos


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
        mock_client = MagicMock()
        expected = [_make_starred("org", "repo")]
        mock_client.get_starred.return_value = expected

        result = get_user_starred("user1", mock_client)
        assert result == expected
        mock_client.get_starred.assert_called_once_with("user1")


class TestWalkStarredRepos:
    """Tests for walk_starred_repos."""

    def test_single_depth(self) -> None:
        mock_client = MagicMock()
        mock_client.get_starred.return_value = [
            _make_starred("org1", "repo1"),
            _make_starred("org2", "repo2"),
        ]

        result = walk_starred_repos("root_user", mock_client, max_depth=1)
        assert len(result) == 2
        assert result[0]["metadata"]["root_user"] == "root_user"
        assert result[0]["metadata"]["depth"] == 0

    def test_cycle_detection(self) -> None:
        mock_client = MagicMock()
        repo1 = _make_starred("org", "repo1")
        repo2 = _make_starred("org", "repo2")

        # Both depth 0 and depth 1 return the same repos
        mock_client.get_starred.side_effect = [
            [repo1, repo2],
            [repo1, repo2],  # duplicates at depth 1
        ]

        result = walk_starred_repos("root_user", mock_client, max_depth=2)
        # Only 2 unique repos, not 4
        assert len(result) == 2

    def test_max_depth_zero(self) -> None:
        mock_client = MagicMock()
        result = walk_starred_repos("root_user", mock_client, max_depth=0)
        assert result == []
        mock_client.get_starred.assert_not_called()

    def test_depth_two_traversal(self) -> None:
        mock_client = MagicMock()

        # Depth 0: root_user starred repo1 (owned by org1) and repo2 (owned by org2)
        depth0_repos = [
            _make_starred("org1", "repo1"),
            _make_starred("org2", "repo2"),
        ]
        # Depth 1: org1 starred repo3, org2 starred repo4
        depth1_repos_org1 = [_make_starred("org3", "repo3")]
        depth1_repos_org2 = [_make_starred("org4", "repo4")]

        mock_client.get_starred.side_effect = [
            depth0_repos,
            depth1_repos_org1,
            depth1_repos_org2,
        ]

        result = walk_starred_repos("root_user", mock_client, max_depth=2)
        assert len(result) == 4
        # Depth 0 repos have depth=0
        assert result[0]["metadata"]["depth"] == 0
        assert result[1]["metadata"]["depth"] == 0
        # Depth 1 repos have depth=1
        assert result[2]["metadata"]["depth"] == 1
        assert result[3]["metadata"]["depth"] == 1

    def test_root_user_excluded_from_next_depth(self) -> None:
        mock_client = MagicMock()

        # root_user starred a repo owned by root_user themselves
        depth0_repos = [_make_starred("root_user", "my-repo")]

        mock_client.get_starred.side_effect = [
            depth0_repos,
            # root_user should NOT be walked again at depth 1
        ]

        result = walk_starred_repos("root_user", mock_client, max_depth=2)
        assert len(result) == 1
        # Only called once (for root_user at depth 0)
        assert mock_client.get_starred.call_count == 1

    def test_visited_parameter_pre_seeds(self) -> None:
        mock_client = MagicMock()
        mock_client.get_starred.return_value = [
            _make_starred("org", "already-seen"),
            _make_starred("org", "new-repo"),
        ]

        visited = {"org/already-seen"}
        result = walk_starred_repos("root_user", mock_client, max_depth=1, visited=visited)
        assert len(result) == 1
        assert result[0]["name"] == "new-repo"

    def test_empty_starred(self) -> None:
        mock_client = MagicMock()
        mock_client.get_starred.return_value = []

        result = walk_starred_repos("root_user", mock_client, max_depth=2)
        assert result == []
