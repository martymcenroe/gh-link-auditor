"""Tests for repo_scout.output_writer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from repo_scout.models import DiscoverySource, make_repo_record
from repo_scout.output_writer import format_for_docfix_bot, write_output


def _repo(owner: str = "org", name: str = "repo") -> dict:
    return make_repo_record(owner=owner, name=name, source=DiscoverySource.AWESOME_LIST)


class TestFormatForDocfixBot:
    """Tests for format_for_docfix_bot."""

    def test_extracts_full_names(self) -> None:
        repos = [_repo("org1", "a"), _repo("org2", "b")]
        result = format_for_docfix_bot(repos)
        assert result == ["org1/a", "org2/b"]

    def test_empty_list(self) -> None:
        assert format_for_docfix_bot([]) == []


class TestWriteOutput:
    """Tests for write_output."""

    def test_json_format(self, tmp_path: Path) -> None:
        repos = [_repo("org", "repo")]
        output = tmp_path / "out.json"
        count = write_output(repos, str(output), fmt="json")

        assert count == 1
        data = json.loads(output.read_text())
        assert len(data) == 1
        assert data[0]["full_name"] == "org/repo"

    def test_jsonl_format(self, tmp_path: Path) -> None:
        repos = [_repo("org", "a"), _repo("org", "b")]
        output = tmp_path / "out.jsonl"
        count = write_output(repos, str(output), fmt="jsonl")

        assert count == 2
        lines = output.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["full_name"] == "org/a"

    def test_txt_format(self, tmp_path: Path) -> None:
        repos = [_repo("org", "a"), _repo("org", "b")]
        output = tmp_path / "out.txt"
        count = write_output(repos, str(output), fmt="txt")

        assert count == 2
        lines = output.read_text().strip().split("\n")
        assert lines == ["org/a", "org/b"]

    def test_unknown_format_raises(self, tmp_path: Path) -> None:
        output = tmp_path / "out.xyz"
        with pytest.raises(ValueError, match="Unknown output format"):
            write_output([], str(output), fmt="xyz")

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        output = tmp_path / "nested" / "dir" / "out.json"
        write_output([], str(output), fmt="json")
        assert output.exists()

    def test_empty_repos(self, tmp_path: Path) -> None:
        output = tmp_path / "empty.json"
        count = write_output([], str(output), fmt="json")
        assert count == 0
        data = json.loads(output.read_text())
        assert data == []
