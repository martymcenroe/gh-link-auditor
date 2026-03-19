"""N0 Load Target node.

Validates target repository (URL or local path), extracts repo name,
and lists documentation files.

See LLD #22 §2.4 for n0_load_target specification.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Literal

from gh_link_auditor.pipeline.state import PipelineState

_DOC_EXTENSIONS = {".md", ".rst", ".txt", ".adoc"}

_URL_PATTERN = re.compile(r"^https?://(github\.com|gitlab\.com|bitbucket\.org)/[^/]+/[^/]+")


def validate_target(target: str) -> tuple[str, Literal["url", "local"]]:
    """Validate target is a valid repo URL or local path.

    Args:
        target: Repository URL or local path.

    Returns:
        Tuple of (normalized_target, target_type).

    Raises:
        ValueError: If target is not a valid URL or local path.
        FileNotFoundError: If local path doesn't exist.
    """
    if not target:
        msg = "Target cannot be empty"
        raise ValueError(msg)

    if _URL_PATTERN.match(target):
        return (target.rstrip("/"), "url")

    target_path = Path(target)
    if target_path.exists() and target_path.is_dir():
        return (str(target_path), "local")

    if target.startswith(("http://", "https://")):
        msg = f"URL does not match expected repository format: {target}"
        raise ValueError(msg)

    # If it looks like a filesystem path (contains separator or starts with / or drive letter),
    # raise FileNotFoundError. Otherwise it's just invalid input.
    if "/" in target or "\\" in target or (len(target) >= 2 and target[1] == ":"):
        msg = f"Local path does not exist: {target}"
        raise FileNotFoundError(msg)

    msg = f"Invalid target: {target}"
    raise ValueError(msg)


def extract_repo_name(target: str, target_type: str) -> str:
    """Extract repo name from URL (org/repo) or local path (dir name).

    Args:
        target: Repository URL or local path.
        target_type: "url" or "local".

    Returns:
        Repo name string.
    """
    if target_type == "url":
        # Extract org/repo from URL like https://github.com/org/repo
        parts = target.rstrip("/").split("/")
        if len(parts) >= 5:
            return f"{parts[-2]}/{parts[-1]}"
        return target

    # Local path: use directory name
    path = Path(target.rstrip("/"))
    return path.name


def _extract_owner_repo(target: str) -> tuple[str, str]:
    """Extract owner and repo from a GitHub URL.

    Args:
        target: Repository URL (e.g., "https://github.com/org/repo").

    Returns:
        Tuple of (owner, repo).
    """
    parts = target.rstrip("/").split("/")
    if len(parts) >= 5:
        return parts[-2], parts[-1]
    return "", ""


def list_documentation_files(
    target: str,
    target_type: str,
    github_client: object | None = None,
) -> list[str]:
    """List all documentation files in target.

    Finds .md, .rst, .txt, .adoc files recursively.
    For local targets, walks the filesystem.
    For URL targets, uses the GitHub Contents API.

    Args:
        target: Repository URL or local path.
        target_type: "url" or "local".
        github_client: Optional GitHubContentsClient instance.
            If None and target_type is "url", creates a new client.

    Returns:
        Sorted list of documentation file paths.
    """
    if target_type == "url":
        owner, repo = _extract_owner_repo(target)
        if not owner or not repo:
            return []
        if github_client is None:
            from gh_link_auditor.github_api import GitHubContentsClient

            github_client = GitHubContentsClient()
        try:
            return github_client.list_doc_files(owner, repo)
        except Exception:
            return []

    target_path = Path(target)
    if not target_path.exists():
        return []

    files = []
    for p in target_path.rglob("*"):
        if p.is_file() and p.suffix.lower() in _DOC_EXTENSIONS:
            files.append(str(p))

    return sorted(files)


def n0_load_target(state: PipelineState) -> PipelineState:
    """N0 node: Load and validate target repository.

    Validates target, extracts repo name, lists documentation files.
    On error, appends to state errors list.

    Args:
        state: Current pipeline state.

    Returns:
        Updated PipelineState.
    """
    target = state.get("target", "")
    verbose = state.get("verbose", False)

    if verbose:
        print(f"[N0] Loading target: {target}", file=sys.stderr, flush=True)

    try:
        normalized, target_type = validate_target(target)
        state["target"] = normalized
        state["target_type"] = target_type
        state["repo_name"] = extract_repo_name(normalized, target_type)

        if target_type == "url":
            owner, repo = _extract_owner_repo(normalized)
            state["repo_owner"] = owner
            state["repo_name_short"] = repo

            # Fetch repo quality and contributing guidelines
            from gh_link_auditor.repo_quality import (
                analyze_contributing_guidelines,
                fetch_contributing_guidelines,
                fetch_repo_metadata,
                format_quality_summary,
            )

            quality = fetch_repo_metadata(owner, repo)
            state["repo_stars"] = quality.stars
            state["repo_pushed_at"] = quality.pushed_at
            state["repo_contributors"] = quality.contributors

            contributing = fetch_contributing_guidelines(owner, repo)
            state["contributing_guidelines"] = contributing
            warnings = analyze_contributing_guidelines(contributing)
            state["contributing_warnings"] = warnings

            if verbose:
                summary = format_quality_summary(quality)
                print(f"[N0] Repo quality: {summary}", file=sys.stderr, flush=True)
                if warnings:
                    for w in warnings:
                        print(f"[N0] Warning: {w}", file=sys.stderr, flush=True)
        else:
            state["repo_owner"] = ""
            state["repo_name_short"] = ""

        if verbose:
            print("[N0] Listing doc files...", file=sys.stderr, flush=True)

        state["doc_files"] = list_documentation_files(normalized, target_type)

        if verbose:
            print(
                f"[N0] Found {len(state['doc_files'])} doc files",
                file=sys.stderr,
                flush=True,
            )
    except (ValueError, FileNotFoundError) as exc:
        state["errors"] = state.get("errors", []) + [str(exc)]

    return state
