"""Automated Git workflow for PR submission.

See LLD #2 §2.4 for git_workflow specification.
Deviation: uses httpx for GitHub API instead of PyGithub.
"""

from __future__ import annotations

import hashlib
import logging
import re
import tempfile
from pathlib import Path

import httpx

from docfix_bot.config import get_user_agent
from docfix_bot.models import (
    BotConfig,
    BrokenLink,
    PRSubmission,
    TargetRepository,
    now_iso,
)

logger = logging.getLogger(__name__)


def create_branch_name(target: TargetRepository, context: str) -> str:
    """Generate a branch name for a fix PR.

    Args:
        target: Target repository.
        context: Context string (e.g., filename).

    Returns:
        Valid git branch name.
    """
    # Sanitize context for git branch name
    safe_context = re.sub(r"[^a-zA-Z0-9-]", "-", context)[:30]
    short_hash = hashlib.sha256(context.encode()).hexdigest()[:8]
    return f"fix/broken-link-{safe_context}-{short_hash}"


def generate_commit_message(broken_links: list[BrokenLink]) -> str:
    """Generate a conventional commit message.

    Args:
        broken_links: List of broken links being fixed.

    Returns:
        Commit message string.
    """
    if len(broken_links) == 1:
        link = broken_links[0]
        return f"fix: correct broken link in {link['source_file']}"

    files = sorted({bl["source_file"] for bl in broken_links})
    if len(files) == 1:
        return f"fix: correct {len(broken_links)} broken links in {files[0]}"

    return f"fix: correct {len(broken_links)} broken links across {len(files)} files"


def clone_repository(
    target: TargetRepository,
    work_dir: Path,
    shallow: bool = True,
) -> Path:
    """Clone repository into work_dir using GitPython.

    All clones happen in temporary directories for isolation.

    Args:
        target: Target repository.
        work_dir: Directory to clone into (must be temp dir).
        shallow: Use shallow clone.

    Returns:
        Path to cloned repository.

    Raises:
        RuntimeError: If clone fails.
    """
    import git

    clone_url = f"https://github.com/{target['owner']}/{target['repo']}.git"
    repo_dir = work_dir / target["repo"]

    try:
        kwargs = {}
        if shallow:
            kwargs["depth"] = 1

        git.Repo.clone_from(clone_url, str(repo_dir), **kwargs)
        return repo_dir
    except git.GitCommandError as e:
        msg = f"Clone failed for {target['owner']}/{target['repo']}: {e}"
        raise RuntimeError(msg) from e


def apply_fixes(
    repo_dir: Path,
    broken_links: list[BrokenLink],
) -> list[str]:
    """Apply link fixes to files in the repository.

    Only applies fixes with suggested_fix and confidence above threshold.

    Args:
        repo_dir: Path to cloned repository.
        broken_links: Links to fix.

    Returns:
        List of modified file paths.
    """
    modified_files: list[str] = []

    for link in broken_links:
        if not link["suggested_fix"] or link["fix_confidence"] < 0.5:
            continue

        file_path = repo_dir / link["source_file"]
        if not file_path.exists():
            continue

        content = file_path.read_text(encoding="utf-8", errors="replace")
        new_content = content.replace(link["original_url"], link["suggested_fix"])

        if new_content != content:
            file_path.write_text(new_content, encoding="utf-8")
            if link["source_file"] not in modified_files:
                modified_files.append(link["source_file"])

    return modified_files


def create_pull_request(
    target: TargetRepository,
    branch_name: str,
    title: str,
    body: str,
    config: BotConfig,
) -> tuple[int | None, str | None]:
    """Create a pull request via GitHub API.

    Args:
        target: Target repository.
        branch_name: Branch to create PR from.
        title: PR title.
        body: PR body/description.
        config: Bot configuration.

    Returns:
        Tuple of (pr_number, pr_url) or (None, None) on failure.
    """
    token = config.get("github_token", "")
    if not token:
        logger.warning("No GitHub token — cannot create PR")
        return (None, None)

    api_url = f"https://api.github.com/repos/{target['owner']}/{target['repo']}/pulls"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": get_user_agent(config),
    }
    payload = {
        "title": title,
        "body": body,
        "head": branch_name,
        "base": "main",
    }

    try:
        response = httpx.post(api_url, json=payload, headers=headers, timeout=30.0)
        if response.status_code == 201:
            data = response.json()
            return (data.get("number"), data.get("html_url"))
        logger.warning("PR creation failed: %d %s", response.status_code, response.text[:200])
        return (None, None)
    except httpx.HTTPError:
        logger.exception("Failed to create PR")
        return (None, None)


def execute_fix_workflow(
    target: TargetRepository,
    broken_links: list[BrokenLink],
    config: BotConfig,
    pr_title: str,
    pr_body: str,
) -> PRSubmission:
    """Execute the full Git workflow to submit a fix PR.

    All operations occur within a temporary directory.

    Args:
        target: Target repository.
        broken_links: Broken links to fix.
        config: Bot configuration.
        pr_title: Pull request title.
        pr_body: Pull request body.

    Returns:
        PRSubmission with results.
    """
    import git

    fixable = [bl for bl in broken_links if bl["suggested_fix"] and bl["fix_confidence"] >= 0.5]
    if not fixable:
        return PRSubmission(
            repository=target,
            branch_name="",
            pr_number=None,
            pr_url=None,
            status="pending",
            broken_links_fixed=[],
            submitted_at=now_iso(),
        )

    with tempfile.TemporaryDirectory() as tmp_dir:
        work_dir = Path(tmp_dir)

        # Step 1: Clone
        repo_dir = clone_repository(target, work_dir, shallow=True)
        repo = git.Repo(str(repo_dir))

        # Step 2: Create branch
        context = fixable[0]["source_file"]
        branch = create_branch_name(target, context)
        repo.git.checkout("-b", branch)

        # Step 3: Apply fixes
        modified = apply_fixes(repo_dir, fixable)
        if not modified:
            return PRSubmission(
                repository=target,
                branch_name=branch,
                pr_number=None,
                pr_url=None,
                status="pending",
                broken_links_fixed=[],
                submitted_at=now_iso(),
            )

        # Step 4: Stage changes
        repo.index.add(modified)

        # Step 5: Commit
        commit_msg = generate_commit_message(fixable)
        repo.index.commit(commit_msg)

        # Step 6: Push
        token = config.get("github_token", "")
        if token:
            push_url = f"https://x-access-token:{token}@github.com/{target['owner']}/{target['repo']}.git"
            repo.git.push(push_url, branch)

        # Step 7: Create PR
        pr_number, pr_url = create_pull_request(target, branch, pr_title, pr_body, config)

    # Temp dir auto-cleaned at this point

    return PRSubmission(
        repository=target,
        branch_name=branch,
        pr_number=pr_number,
        pr_url=pr_url,
        status="submitted" if pr_number else "pending",
        broken_links_fixed=fixable,
        submitted_at=now_iso(),
    )
