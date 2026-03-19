"""N6 Submit PR node.

Forks the target repo, applies fixes, and submits a PR from the fork.
Only runs for URL targets with approved fixes (not dry-run).

See Issue #84 for specification.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

from gh_link_auditor.pipeline.state import FixPatch, PipelineState

logger = logging.getLogger(__name__)


def _run_gh(args: list[str], cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    """Run a gh CLI command.

    Args:
        args: Arguments to pass to gh.
        cwd: Working directory.

    Returns:
        CompletedProcess result.

    Raises:
        RuntimeError: If the command fails.
    """
    cmd = ["gh", *args]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=120,
            check=False,
        )
        if result.returncode != 0:
            msg = f"gh command failed: {' '.join(cmd)}\nstderr: {result.stderr.strip()}"
            raise RuntimeError(msg)
        return result
    except FileNotFoundError as exc:
        msg = "gh CLI not found. Install GitHub CLI: https://cli.github.com/"
        raise RuntimeError(msg) from exc


def _fork_repo(owner: str, repo: str) -> str:
    """Fork a repository via gh CLI. Returns the fork's full name (owner/repo).

    Args:
        owner: Upstream repository owner.
        repo: Repository name.

    Returns:
        Fork full name, e.g. "martymcenroe/flask".
    """
    _run_gh(
        [
            "repo",
            "fork",
            f"{owner}/{repo}",
            "--clone=false",
        ]
    )
    # gh repo fork prints the fork name or "already exists" message.
    # Parse the fork owner from the output or default to authenticated user.
    auth_result = _run_gh(["auth", "status", "--hostname", "github.com"])
    # Extract username from auth status output
    for line in auth_result.stderr.splitlines() + auth_result.stdout.splitlines():
        if "Logged in to" in line and "account" in line:
            # "Logged in to github.com account martymcenroe"
            parts = line.strip().split()
            for i, part in enumerate(parts):
                if part == "account":
                    return f"{parts[i + 1].rstrip('(').rstrip(')')}/{repo}"
    # Fallback: try gh api to get authenticated user
    user_result = _run_gh(["api", "user", "--jq", ".login"])
    username = user_result.stdout.strip()
    if username:
        return f"{username}/{repo}"
    msg = "Could not determine fork owner from gh auth status"
    raise RuntimeError(msg)


def _clone_fork(fork_full_name: str, work_dir: Path) -> Path:
    """Shallow clone the fork.

    Args:
        fork_full_name: Fork in "owner/repo" format.
        work_dir: Directory to clone into.

    Returns:
        Path to cloned repository.
    """
    repo_name = fork_full_name.split("/")[-1]
    repo_dir = work_dir / repo_name
    _run_gh(
        [
            "repo",
            "clone",
            fork_full_name,
            str(repo_dir),
            "--",
            "--depth=1",
        ]
    )
    return repo_dir


def _apply_fixes(repo_dir: Path, fixes: list[FixPatch]) -> list[str]:
    """Apply URL replacements to files in the cloned repo.

    Uses str.replace() — no regex.

    Args:
        repo_dir: Path to cloned repository.
        fixes: List of fixes to apply.

    Returns:
        List of modified file paths (relative to repo root).
    """
    modified: list[str] = []
    for fix in fixes:
        file_path = repo_dir / fix["source_file"]
        if not file_path.exists():
            logger.warning("File not found in clone: %s", fix["source_file"])
            continue

        content = file_path.read_text(encoding="utf-8", errors="replace")
        new_content = content.replace(fix["original_url"], fix["replacement_url"])

        if new_content != content:
            file_path.write_text(new_content, encoding="utf-8")
            if fix["source_file"] not in modified:
                modified.append(fix["source_file"])

    return modified


def _get_default_branch(owner: str, repo: str) -> str:
    """Get the default branch of the upstream repo.

    Args:
        owner: Repository owner.
        repo: Repository name.

    Returns:
        Default branch name (e.g. "main").
    """
    result = _run_gh(
        [
            "api",
            f"repos/{owner}/{repo}",
            "--jq",
            ".default_branch",
        ]
    )
    branch = result.stdout.strip()
    return branch or "main"


def _generate_commit_message(fixes: list[FixPatch]) -> str:
    """Generate a commit message for the fixes.

    Args:
        fixes: List of applied fixes.

    Returns:
        Commit message string.
    """
    if len(fixes) == 1:
        return f"docs: fix broken link in {fixes[0]['source_file']}"

    files = sorted({f["source_file"] for f in fixes})
    if len(files) == 1:
        return f"docs: fix {len(fixes)} broken links in {files[0]}"

    return f"docs: fix {len(fixes)} broken links across {len(files)} files"


def n6_submit_pr(state: PipelineState) -> PipelineState:
    """N6 node: Fork target repo, apply fixes, submit PR.

    Skips if:
    - dry_run is set
    - no fixes available
    - target_type is not "url"

    Args:
        state: Current pipeline state.

    Returns:
        Updated PipelineState with pr_url and pr_number.
    """
    fixes = state.get("fixes", [])

    if not fixes:
        logger.info("N6: No fixes to submit")
        return state

    if state.get("dry_run", False):
        logger.info("N6: Dry run — skipping PR submission")
        return state

    target_type = state.get("target_type", "local")
    if target_type != "url":
        logger.info("N6: Local target — skipping PR submission")
        return state

    repo_owner = state.get("repo_owner", "")
    repo_name_short = state.get("repo_name_short", "")
    if not repo_owner or not repo_name_short:
        state["errors"] = state.get("errors", []) + ["N6: Cannot submit PR — missing owner/repo"]
        return state

    try:
        # Step 1: Fork
        fork_full_name = _fork_repo(repo_owner, repo_name_short)
        logger.info("N6: Fork ready: %s", fork_full_name)

        with tempfile.TemporaryDirectory(prefix="ghla-pr-") as tmp_dir:
            work_dir = Path(tmp_dir)

            # Step 2: Clone fork
            repo_dir = _clone_fork(fork_full_name, work_dir)

            # Step 3: Create branch
            branch_name = "fix/dead-links"
            subprocess.run(
                ["git", "checkout", "-b", branch_name],
                cwd=str(repo_dir),
                capture_output=True,
                text=True,
                check=True,
            )

            # Step 4: Apply fixes
            modified = _apply_fixes(repo_dir, fixes)
            if not modified:
                logger.warning("N6: No files were modified after applying fixes")
                return state

            # Step 5: Commit
            subprocess.run(
                ["git", "add"] + modified,
                cwd=str(repo_dir),
                capture_output=True,
                text=True,
                check=True,
            )
            commit_msg = _generate_commit_message(fixes)
            subprocess.run(
                ["git", "commit", "-m", commit_msg],
                cwd=str(repo_dir),
                capture_output=True,
                text=True,
                check=True,
            )

            # Step 6: Push to fork
            subprocess.run(
                ["git", "push", "origin", branch_name],
                cwd=str(repo_dir),
                capture_output=True,
                text=True,
                check=True,
            )

            # Step 7: Generate PR title and body
            from gh_link_auditor.pipeline.pr_message import (
                generate_pr_body_from_fixes,
                generate_pr_title_from_fixes,
            )

            pr_title = generate_pr_title_from_fixes(fixes)
            verdicts = state.get("reviewed_verdicts", [])
            pr_body = generate_pr_body_from_fixes(fixes, verdicts)

            # Step 8: Create PR from fork → upstream
            default_branch = _get_default_branch(repo_owner, repo_name_short)
            fork_owner = fork_full_name.split("/")[0]

            result = _run_gh(
                [
                    "pr",
                    "create",
                    "--repo",
                    f"{repo_owner}/{repo_name_short}",
                    "--head",
                    f"{fork_owner}:{branch_name}",
                    "--base",
                    default_branch,
                    "--title",
                    pr_title,
                    "--body",
                    pr_body,
                ]
            )

            # Parse PR URL from output
            pr_url = result.stdout.strip()
            # Extract PR number from URL
            pr_number = _extract_pr_number(pr_url)

            state["pr_url"] = pr_url
            state["pr_number"] = pr_number
            logger.info("N6: PR created: %s", pr_url)

    except RuntimeError as exc:
        state["errors"] = state.get("errors", []) + [f"N6: {exc}"]
        logger.error("N6: PR submission failed: %s", exc)
    except subprocess.CalledProcessError as exc:
        state["errors"] = state.get("errors", []) + [f"N6: git command failed: {exc.cmd} — {exc.stderr}"]
        logger.error("N6: git command failed: %s", exc)

    return state


def _extract_pr_number(pr_url: str) -> int:
    """Extract PR number from a GitHub PR URL.

    Args:
        pr_url: URL like "https://github.com/owner/repo/pull/123".

    Returns:
        PR number, or 0 if parsing fails.
    """
    try:
        parts = pr_url.rstrip("/").split("/")
        return int(parts[-1])
    except (ValueError, IndexError):
        return 0
