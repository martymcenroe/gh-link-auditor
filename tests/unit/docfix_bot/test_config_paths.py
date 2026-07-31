"""Config paths must live under data-g/, not the gitignored data/ (#413)."""

from __future__ import annotations

from pathlib import Path

from docfix_bot.config import get_default_config

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_KEYS = ("targets_path", "blocklist_path")


class TestConfigPathsAreGitTracked:
    def test_defaults_point_at_data_g(self):
        """The fleet-wide global gitignore excludes /data/, so hand-authored
        config there cannot be committed once it is not already tracked.
        data-g/ is the git-tracked sibling (AssemblyZero #1563).
        """
        config = get_default_config()
        for key in CONFIG_KEYS:
            value = config[key]
            assert value.startswith("data-g/"), f"{key} = {value!r} must live under data-g/"
            assert not value.startswith("data/"), f"{key} = {value!r} is under the ignored data/"

    def test_referenced_config_files_exist_on_disk(self):
        """A default path that points at nothing is a silent runtime failure."""
        config = get_default_config()
        for key in CONFIG_KEYS:
            path = REPO_ROOT / config[key]
            assert path.is_file(), f"{key} -> {path} does not exist"

    def test_no_config_files_left_behind_under_data(self):
        """Asserts on FILES, not the directory.

        `git mv` removes the tracked files but leaves the now-empty
        `data/config/` behind, and so does pulling this change on another
        machine. An assertion on directory existence would therefore fail
        for every operator after they pull, which is a broken test rather
        than a real finding.
        """
        stale = sorted(p.name for p in (REPO_ROOT / "data" / "config").glob("*.yaml"))
        assert not stale, f"config still present under the ignored data/: {stale}"
