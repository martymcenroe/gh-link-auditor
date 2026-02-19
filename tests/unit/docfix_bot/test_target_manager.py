"""Tests for docfix_bot.target_manager."""

from __future__ import annotations

from pathlib import Path

import pytest

from docfix_bot.models import make_target
from docfix_bot.target_manager import (
    check_contributing_md,
    is_blocklisted,
    load_targets,
    prioritize_targets,
)


class TestLoadTargets:
    def test_valid_yaml(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "targets.yaml"
        yaml_file.write_text("""repositories:
  - owner: org1
    repo: repo1
    priority: 8
  - owner: org2
    repo: repo2
""")
        targets = load_targets(yaml_file)
        assert len(targets) == 2
        assert targets[0]["owner"] == "org1"
        assert targets[0]["priority"] == 8
        assert targets[1]["priority"] == 5  # default

    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="not found"):
            load_targets(tmp_path / "missing.yaml")

    def test_invalid_yaml_no_repos_key(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "targets.yaml"
        yaml_file.write_text("something_else: true\n")
        with pytest.raises(ValueError, match="missing 'repositories'"):
            load_targets(yaml_file)

    def test_repos_not_list(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "targets.yaml"
        yaml_file.write_text("repositories: not-a-list\n")
        with pytest.raises(ValueError, match="must be a list"):
            load_targets(yaml_file)

    def test_skips_invalid_entries(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "targets.yaml"
        yaml_file.write_text("""repositories:
  - owner: org1
    repo: repo1
  - invalid_entry: true
  - just_a_string
""")
        targets = load_targets(yaml_file)
        assert len(targets) == 1

    def test_enabled_default_true(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "targets.yaml"
        yaml_file.write_text("""repositories:
  - owner: org1
    repo: repo1
""")
        targets = load_targets(yaml_file)
        assert targets[0]["enabled"] is True

    def test_disabled_target(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "targets.yaml"
        yaml_file.write_text("""repositories:
  - owner: org1
    repo: repo1
    enabled: false
""")
        targets = load_targets(yaml_file)
        assert targets[0]["enabled"] is False


class TestPrioritizeTargets:
    def test_sort_by_priority(self) -> None:
        targets = [
            make_target("a", "low", priority=1),
            make_target("b", "high", priority=10),
        ]
        result = prioritize_targets(targets)
        assert result[0]["repo"] == "high"

    def test_filters_disabled(self) -> None:
        targets = [
            make_target("a", "enabled", enabled=True),
            make_target("b", "disabled", enabled=False),
        ]
        result = prioritize_targets(targets)
        assert len(result) == 1
        assert result[0]["repo"] == "enabled"

    def test_least_recently_scanned_first(self) -> None:
        t1 = make_target("a", "old", priority=5)
        t1["last_scanned"] = "2024-01-01T00:00:00"
        t2 = make_target("b", "new", priority=5)
        t2["last_scanned"] = "2024-06-01T00:00:00"
        result = prioritize_targets([t2, t1])
        assert result[0]["repo"] == "old"

    def test_never_scanned_first(self) -> None:
        t1 = make_target("a", "scanned", priority=5)
        t1["last_scanned"] = "2024-01-01T00:00:00"
        t2 = make_target("b", "never", priority=5)
        result = prioritize_targets([t1, t2])
        assert result[0]["repo"] == "never"

    def test_empty_list(self) -> None:
        assert prioritize_targets([]) == []


class TestIsBlocklisted:
    def test_not_blocklisted(self, tmp_path: Path) -> None:
        blocklist = tmp_path / "blocklist.yaml"
        blocklist.write_text("blocked:\n  - other/repo\n")
        target = make_target("org", "repo")
        assert is_blocklisted(target, blocklist) is False

    def test_blocklisted(self, tmp_path: Path) -> None:
        blocklist = tmp_path / "blocklist.yaml"
        blocklist.write_text("blocked:\n  - org/repo\n")
        target = make_target("org", "repo")
        assert is_blocklisted(target, blocklist) is True

    def test_no_blocklist_file(self, tmp_path: Path) -> None:
        target = make_target("org", "repo")
        assert is_blocklisted(target, tmp_path / "missing.yaml") is False

    def test_invalid_blocklist(self, tmp_path: Path) -> None:
        blocklist = tmp_path / "blocklist.yaml"
        blocklist.write_text("something: else\n")
        target = make_target("org", "repo")
        assert is_blocklisted(target, blocklist) is False

    def test_blocked_not_list(self, tmp_path: Path) -> None:
        blocklist = tmp_path / "blocklist.yaml"
        blocklist.write_text("blocked: not-a-list\n")
        target = make_target("org", "repo")
        assert is_blocklisted(target, blocklist) is False


class TestCheckContributingMd:
    def test_no_contributing_file(self, tmp_path: Path) -> None:
        assert check_contributing_md(tmp_path) is True

    def test_allows_contributions(self, tmp_path: Path) -> None:
        (tmp_path / "CONTRIBUTING.md").write_text("# Contributing\nPRs welcome!\n")
        assert check_contributing_md(tmp_path) is True

    def test_no_bots(self, tmp_path: Path) -> None:
        (tmp_path / "CONTRIBUTING.md").write_text("# Contributing\nNo bots allowed.\n")
        assert check_contributing_md(tmp_path) is False

    def test_no_automated(self, tmp_path: Path) -> None:
        (tmp_path / "CONTRIBUTING.md").write_text("Do not submit automated PRs.\n")
        assert check_contributing_md(tmp_path) is False

    def test_case_insensitive(self, tmp_path: Path) -> None:
        (tmp_path / "CONTRIBUTING.md").write_text("NO BOTS please.\n")
        assert check_contributing_md(tmp_path) is False
