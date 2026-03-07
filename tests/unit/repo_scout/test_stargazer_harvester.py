"""Tests for repo_scout.stargazer_harvester."""

from __future__ import annotations

from unittest.mock import MagicMock

from repo_scout.models import DiscoverySource, make_repo_record
from repo_scout.stargazer_harvester import (
    _is_recently_active,
    harvest_from_stargazers,
)


def _make_user_repo(
    owner: str = "user1",
    name: str = "my-tool",
    pushed_at: str | None = "2026-02-01T00:00:00Z",
    has_issues: bool = True,
    language: str | None = "Python",
    fork: bool = False,
    archived: bool = False,
    stars: int = 10,
    description: str | None = "A tool",
) -> dict:
    """Build a fake GitHub repo API response dict."""
    return {
        "owner": {"login": owner},
        "name": name,
        "description": description,
        "stargazers_count": stars,
        "pushed_at": pushed_at,
        "has_issues": has_issues,
        "language": language,
        "fork": fork,
        "archived": archived,
    }


class TestIsRecentlyActive:
    """Tests for _is_recently_active helper."""

    def test_recent_date_returns_true(self) -> None:
        assert _is_recently_active("2026-02-01T00:00:00Z", 6) is True

    def test_old_date_returns_false(self) -> None:
        assert _is_recently_active("2020-01-01T00:00:00Z", 6) is False

    def test_none_returns_false(self) -> None:
        assert _is_recently_active(None, 6) is False

    def test_boundary_exact_age(self) -> None:
        # 6 months * 30 days = 180 days; use a date within that window
        assert _is_recently_active("2025-10-01T00:00:00Z", 6) is True


class TestHarvestFromStargazers:
    """Tests for harvest_from_stargazers."""

    def test_basic_harvest(self) -> None:
        client = MagicMock()
        client.get_stargazers.return_value = ["alice"]
        client.get_user_repos.return_value = [
            make_repo_record(
                owner="alice",
                name="cool-tool",
                source=DiscoverySource.STARGAZER_TARGET,
                metadata={
                    "seed_repo": "anthropics/claude-code",
                    "stargazer_username": "alice",
                    "pushed_at": "2026-02-01T00:00:00Z",
                    "has_issues": True,
                    "language": "Python",
                },
            )
        ]

        result = harvest_from_stargazers(
            seed_repos=["anthropics/claude-code"],
            github_client=client,
            max_stargazers=100,
            max_repo_age_months=6,
        )
        assert len(result) == 1
        assert result[0]["owner"] == "alice"
        assert result[0]["sources"] == ["stargazer_target"]

    def test_empty_stargazers_returns_empty(self) -> None:
        client = MagicMock()
        client.get_stargazers.return_value = []

        result = harvest_from_stargazers(
            seed_repos=["org/repo"],
            github_client=client,
        )
        assert result == []
        client.get_user_repos.assert_not_called()

    def test_max_stargazers_respected(self) -> None:
        client = MagicMock()
        client.get_stargazers.return_value = ["u1", "u2", "u3"]
        client.get_user_repos.return_value = []

        harvest_from_stargazers(
            seed_repos=["org/repo"],
            github_client=client,
            max_stargazers=50,
        )
        client.get_stargazers.assert_called_once_with("org", "repo", max_count=50)

    def test_duplicate_stargazers_across_seeds_processed_once(self) -> None:
        client = MagicMock()
        # Both seeds return the same stargazer
        client.get_stargazers.side_effect = [["alice"], ["alice"]]
        client.get_user_repos.return_value = []

        harvest_from_stargazers(
            seed_repos=["org/repo1", "org/repo2"],
            github_client=client,
        )
        # get_user_repos should only be called once for alice
        assert client.get_user_repos.call_count == 1

    def test_repo_age_filtering_old_repo_excluded(self) -> None:
        client = MagicMock()
        client.get_stargazers.return_value = ["alice"]
        # get_user_repos returns a repo but with old pushed_at
        old_repo = make_repo_record(
            owner="alice",
            name="old-repo",
            source=DiscoverySource.STARGAZER_TARGET,
            metadata={
                "seed_repo": "org/repo",
                "stargazer_username": "alice",
                "pushed_at": "2020-01-01T00:00:00Z",
                "has_issues": True,
                "language": "Python",
            },
        )
        client.get_user_repos.return_value = [old_repo]

        result = harvest_from_stargazers(
            seed_repos=["org/repo"],
            github_client=client,
            max_repo_age_months=6,
        )
        assert result == []

    def test_repo_age_filtering_recent_repo_included(self) -> None:
        client = MagicMock()
        client.get_stargazers.return_value = ["alice"]
        recent_repo = make_repo_record(
            owner="alice",
            name="new-repo",
            source=DiscoverySource.STARGAZER_TARGET,
            metadata={
                "seed_repo": "org/repo",
                "stargazer_username": "alice",
                "pushed_at": "2026-02-01T00:00:00Z",
                "has_issues": True,
                "language": "Python",
            },
        )
        client.get_user_repos.return_value = [recent_repo]

        result = harvest_from_stargazers(
            seed_repos=["org/repo"],
            github_client=client,
            max_repo_age_months=6,
        )
        assert len(result) == 1

    def test_repo_age_filtering_none_pushed_at_excluded(self) -> None:
        client = MagicMock()
        client.get_stargazers.return_value = ["alice"]
        no_push_repo = make_repo_record(
            owner="alice",
            name="no-push",
            source=DiscoverySource.STARGAZER_TARGET,
            metadata={
                "seed_repo": "org/repo",
                "stargazer_username": "alice",
                "pushed_at": None,
                "has_issues": True,
                "language": None,
            },
        )
        client.get_user_repos.return_value = [no_push_repo]

        result = harvest_from_stargazers(
            seed_repos=["org/repo"],
            github_client=client,
            max_repo_age_months=6,
        )
        assert result == []

    def test_metadata_includes_seed_and_stargazer(self) -> None:
        client = MagicMock()
        client.get_stargazers.return_value = ["bob"]
        repo = make_repo_record(
            owner="bob",
            name="tool",
            source=DiscoverySource.STARGAZER_TARGET,
            metadata={
                "seed_repo": "anthropics/claude-code",
                "stargazer_username": "bob",
                "pushed_at": "2026-02-15T00:00:00Z",
                "has_issues": True,
                "language": "TypeScript",
            },
        )
        client.get_user_repos.return_value = [repo]

        result = harvest_from_stargazers(
            seed_repos=["anthropics/claude-code"],
            github_client=client,
        )
        assert result[0]["metadata"]["seed_repo"] == "anthropics/claude-code"
        assert result[0]["metadata"]["stargazer_username"] == "bob"

    def test_invalid_seed_repo_format_skipped(self) -> None:
        client = MagicMock()

        result = harvest_from_stargazers(
            seed_repos=["invalid-no-slash"],
            github_client=client,
        )
        assert result == []
        client.get_stargazers.assert_not_called()

    def test_progress_callback_invoked(self) -> None:
        client = MagicMock()
        client.get_stargazers.return_value = ["alice"]
        client.get_user_repos.return_value = []
        callback = MagicMock()

        harvest_from_stargazers(
            seed_repos=["org/repo"],
            github_client=client,
            progress_callback=callback,
        )
        assert callback.call_count >= 1

    def test_source_is_stargazer_target(self) -> None:
        client = MagicMock()
        client.get_stargazers.return_value = ["alice"]
        repo = make_repo_record(
            owner="alice",
            name="tool",
            source=DiscoverySource.STARGAZER_TARGET,
            metadata={
                "seed_repo": "org/repo",
                "stargazer_username": "alice",
                "pushed_at": "2026-02-01T00:00:00Z",
                "has_issues": True,
                "language": "Python",
            },
        )
        client.get_user_repos.return_value = [repo]

        result = harvest_from_stargazers(
            seed_repos=["org/repo"],
            github_client=client,
        )
        assert result[0]["sources"] == ["stargazer_target"]

    def test_multiple_seeds_aggregate_results(self) -> None:
        client = MagicMock()
        client.get_stargazers.side_effect = [["alice"], ["bob"]]
        repo_a = make_repo_record(
            owner="alice",
            name="a-tool",
            source=DiscoverySource.STARGAZER_TARGET,
            metadata={
                "seed_repo": "org/r1",
                "stargazer_username": "alice",
                "pushed_at": "2026-02-01T00:00:00Z",
                "has_issues": True,
                "language": None,
            },
        )
        repo_b = make_repo_record(
            owner="bob",
            name="b-tool",
            source=DiscoverySource.STARGAZER_TARGET,
            metadata={
                "seed_repo": "org/r2",
                "stargazer_username": "bob",
                "pushed_at": "2026-02-01T00:00:00Z",
                "has_issues": True,
                "language": None,
            },
        )
        client.get_user_repos.side_effect = [[repo_a], [repo_b]]

        result = harvest_from_stargazers(
            seed_repos=["org/r1", "org/r2"],
            github_client=client,
        )
        assert len(result) == 2
