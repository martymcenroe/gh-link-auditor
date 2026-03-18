"""N5 Generate Fix node.

Generates unified diff patches for approved replacements.
For URL targets, clones the repository first (clone-last architecture).

See LLD #22 §2.4 and LLD #67 for specification.
"""

from __future__ import annotations

import difflib
import logging
import tempfile
from pathlib import Path

from gh_link_auditor.pipeline.state import FixPatch, PipelineState

logger = logging.getLogger(__name__)


def _clone_repo(owner: str, repo: str, work_dir: Path) -> Path:
    """Shallow clone a repository into work_dir.

    Args:
        owner: Repository owner.
        repo: Repository name.
        work_dir: Directory to clone into.

    Returns:
        Path to cloned repository.

    Raises:
        RuntimeError: If clone fails.
    """
    import git

    clone_url = f"https://github.com/{owner}/{repo}.git"
    repo_dir = work_dir / repo

    try:
        git.Repo.clone_from(clone_url, str(repo_dir), depth=1)
        return repo_dir
    except git.GitCommandError as exc:
        msg = f"Failed to clone {owner}/{repo}: {exc}"
        raise RuntimeError(msg) from exc


def generate_unified_diff(
    file_path: str,
    original_url: str,
    replacement_url: str,
) -> str:
    """Generate unified diff for a single URL replacement.

    Args:
        file_path: Path to the file containing the URL.
        original_url: URL to replace.
        replacement_url: New URL.

    Returns:
        Unified diff string, or empty string if no changes.
    """
    try:
        content = Path(file_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        logger.warning("Cannot read file: %s", file_path)
        return ""

    if original_url not in content:
        return ""

    new_content = content.replace(original_url, replacement_url)

    original_lines = content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)

    diff_lines = list(
        difflib.unified_diff(
            original_lines,
            new_lines,
            fromfile=f"a/{Path(file_path).name}",
            tofile=f"b/{Path(file_path).name}",
        )
    )

    if not diff_lines:
        return ""

    return "".join(diff_lines)


def n5_generate_fix(state: PipelineState) -> PipelineState:
    """N5 node: Generate fix patches for approved replacements.

    For each approved verdict with a candidate, generates a unified diff.
    For URL targets, clones the repository first to access files locally.

    Args:
        state: Current pipeline state.

    Returns:
        Updated PipelineState with fixes populated.
    """
    reviewed = state.get("reviewed_verdicts", [])
    fixes: list[FixPatch] = []
    target_type = state.get("target_type", "local")

    if not reviewed or not any(v.get("approved") and v.get("candidate") for v in reviewed):
        state["fixes"] = fixes
        return state

    clone_dir = None

    if target_type == "url":
        repo_owner = state.get("repo_owner", "")
        repo_name_short = state.get("repo_name_short", "")
        if not repo_owner or not repo_name_short:
            state["errors"] = state.get("errors", []) + ["Cannot generate fixes for URL target: missing owner/repo"]
            state["fixes"] = fixes
            return state

        try:
            tmp_dir = tempfile.mkdtemp(prefix="ghla-fix-")
            clone_dir = _clone_repo(repo_owner, repo_name_short, Path(tmp_dir))
        except RuntimeError as exc:
            state["errors"] = state.get("errors", []) + [str(exc)]
            state["fixes"] = fixes
            return state

    for verdict in reviewed:
        if not verdict.get("approved"):
            continue

        candidate = verdict.get("candidate")
        if not candidate:
            continue

        dead_link = verdict["dead_link"]
        source_file = dead_link["source_file"]
        original_url = dead_link["url"]
        replacement_url = candidate["url"]

        if target_type == "url" and clone_dir is not None:
            file_path = str(clone_dir / source_file)
        else:
            file_path = source_file

        diff = generate_unified_diff(file_path, original_url, replacement_url)
        if diff:
            fixes.append(
                FixPatch(
                    source_file=source_file,
                    original_url=original_url,
                    replacement_url=replacement_url,
                    unified_diff=diff,
                )
            )

    state["fixes"] = fixes
    return state
