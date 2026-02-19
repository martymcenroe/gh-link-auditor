"""Tests for N0 Load Target node.

See LLD #22 §10.0 T010-T050: N0 validation and file listing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gh_link_auditor.pipeline.nodes.n0_load_target import (
    extract_repo_name,
    list_documentation_files,
    n0_load_target,
    validate_target,
)
from gh_link_auditor.pipeline.state import create_initial_state


class TestValidateTarget:
    """Tests for validate_target()."""

    def test_accepts_github_url(self) -> None:
        target, target_type = validate_target("https://github.com/org/repo")
        assert target_type == "url"
        assert target == "https://github.com/org/repo"

    def test_accepts_github_url_with_trailing_slash(self) -> None:
        target, target_type = validate_target("https://github.com/org/repo/")
        assert target_type == "url"

    def test_accepts_gitlab_url(self) -> None:
        target, target_type = validate_target("https://gitlab.com/org/repo")
        assert target_type == "url"

    def test_accepts_local_path(self, tmp_path: Path) -> None:
        target, target_type = validate_target(str(tmp_path))
        assert target_type == "local"
        assert target == str(tmp_path)

    def test_rejects_invalid_url(self) -> None:
        with pytest.raises(ValueError):
            validate_target("not-a-url")

    def test_rejects_nonexistent_path(self) -> None:
        with pytest.raises(FileNotFoundError):
            validate_target("/nonexistent/path/that/does/not/exist")

    def test_rejects_empty_string(self) -> None:
        with pytest.raises(ValueError):
            validate_target("")

    def test_accepts_http_github_url(self) -> None:
        target, target_type = validate_target("http://github.com/org/repo")
        assert target_type == "url"

    def test_rejects_non_repo_url(self) -> None:
        with pytest.raises(ValueError, match="does not match expected repository format"):
            validate_target("https://example.com/not-a-repo")


class TestExtractRepoName:
    """Tests for extract_repo_name()."""

    def test_github_url(self) -> None:
        name = extract_repo_name("https://github.com/org/repo", "url")
        assert name == "org/repo"

    def test_github_url_with_trailing_slash(self) -> None:
        name = extract_repo_name("https://github.com/org/repo/", "url")
        assert name == "org/repo"

    def test_gitlab_url(self) -> None:
        name = extract_repo_name("https://gitlab.com/org/repo", "url")
        assert name == "org/repo"

    def test_local_path(self, tmp_path: Path) -> None:
        name = extract_repo_name(str(tmp_path), "local")
        assert name == tmp_path.name

    def test_local_path_with_trailing_separator(self, tmp_path: Path) -> None:
        name = extract_repo_name(str(tmp_path) + "/", "local")
        assert name == tmp_path.name

    def test_short_url_fallback(self) -> None:
        """URL with fewer than 5 parts returns full target."""
        name = extract_repo_name("https://short.url", "url")
        assert name == "https://short.url"


class TestListDocumentationFiles:
    """Tests for list_documentation_files()."""

    def test_finds_markdown_files(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text("# Hello")
        (tmp_path / "CONTRIBUTING.md").write_text("# Contrib")
        files = list_documentation_files(str(tmp_path), "local")
        assert len(files) == 2

    def test_finds_rst_files(self, tmp_path: Path) -> None:
        (tmp_path / "index.rst").write_text("Title\n=====")
        files = list_documentation_files(str(tmp_path), "local")
        assert len(files) == 1

    def test_finds_txt_files(self, tmp_path: Path) -> None:
        (tmp_path / "notes.txt").write_text("Some notes")
        files = list_documentation_files(str(tmp_path), "local")
        assert len(files) == 1

    def test_finds_adoc_files(self, tmp_path: Path) -> None:
        (tmp_path / "guide.adoc").write_text("= Guide")
        files = list_documentation_files(str(tmp_path), "local")
        assert len(files) == 1

    def test_excludes_python_files(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text("# Hi")
        (tmp_path / "main.py").write_text("print('hi')")
        files = list_documentation_files(str(tmp_path), "local")
        assert len(files) == 1
        assert files[0].endswith(".md")

    def test_finds_nested_files(self, tmp_path: Path) -> None:
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "guide.md").write_text("# Guide")
        (tmp_path / "README.md").write_text("# Root")
        files = list_documentation_files(str(tmp_path), "local")
        assert len(files) == 2

    def test_returns_empty_for_no_docs(self, tmp_path: Path) -> None:
        (tmp_path / "main.py").write_text("print()")
        files = list_documentation_files(str(tmp_path), "local")
        assert files == []

    def test_returns_sorted_paths(self, tmp_path: Path) -> None:
        (tmp_path / "z.md").write_text("z")
        (tmp_path / "a.md").write_text("a")
        files = list_documentation_files(str(tmp_path), "local")
        assert files == sorted(files)

    def test_returns_empty_for_url_type(self) -> None:
        files = list_documentation_files("https://github.com/org/repo", "url")
        assert files == []

    def test_returns_empty_for_nonexistent_path(self) -> None:
        files = list_documentation_files("/nonexistent/path/xyzzy", "local")
        assert files == []


class TestN0LoadTarget:
    """Tests for n0_load_target() node function."""

    def test_sets_target_type_for_local(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text("# Test")
        state = create_initial_state(target=str(tmp_path))
        result = n0_load_target(state)
        assert result["target_type"] == "local"

    def test_sets_repo_name_for_local(self, tmp_path: Path) -> None:
        state = create_initial_state(target=str(tmp_path))
        result = n0_load_target(state)
        assert result["repo_name"] == tmp_path.name

    def test_sets_doc_files_for_local(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text("# Test")
        (tmp_path / "guide.md").write_text("# Guide")
        state = create_initial_state(target=str(tmp_path))
        result = n0_load_target(state)
        assert len(result["doc_files"]) == 2

    def test_appends_error_on_invalid_target(self) -> None:
        state = create_initial_state(target="not-valid-at-all")
        result = n0_load_target(state)
        assert len(result["errors"]) > 0

    def test_sets_target_type_for_url(self) -> None:
        state = create_initial_state(target="https://github.com/org/repo")
        result = n0_load_target(state)
        assert result["target_type"] == "url"

    def test_sets_repo_name_for_url(self) -> None:
        state = create_initial_state(target="https://github.com/org/repo")
        result = n0_load_target(state)
        assert result["repo_name"] == "org/repo"
