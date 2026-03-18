"""N1 Scan node (Lu-Tze).

Wraps existing link-checking modules to scan documentation files
for dead links.

See LLD #22 §2.4 for n1_scan specification.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from gh_link_auditor.network import check_url as network_check_url
from gh_link_auditor.pipeline.state import DeadLink, PipelineState

_URL_RE = re.compile(r"https?://[^\s\)>\"\]]+")


def _read_file_content(
    filepath: str,
    target_type: str = "local",
    repo_owner: str = "",
    repo_name_short: str = "",
    github_client: object | None = None,
) -> str:
    """Read file content from local filesystem or GitHub API.

    Args:
        filepath: File path (absolute for local, relative for URL targets).
        target_type: "url" or "local".
        repo_owner: Repository owner (for URL targets).
        repo_name_short: Repository name (for URL targets).
        github_client: Optional GitHubContentsClient instance.

    Returns:
        File content as string.

    Raises:
        OSError: If file cannot be read.
    """
    if target_type == "url":
        if github_client is None:
            from gh_link_auditor.github_api import GitHubContentsClient

            github_client = GitHubContentsClient()
        return github_client.fetch_file_content(repo_owner, repo_name_short, filepath)

    return Path(filepath).read_text(encoding="utf-8", errors="replace")


def _extract_urls_from_file(
    filepath: str,
    target_type: str = "local",
    repo_owner: str = "",
    repo_name_short: str = "",
    github_client: object | None = None,
) -> list[tuple[str, int, str]]:
    """Extract URLs from a documentation file.

    Args:
        filepath: Path to documentation file.
        target_type: "url" or "local".
        repo_owner: Repository owner (for URL targets).
        repo_name_short: Repository name (for URL targets).
        github_client: Optional GitHubContentsClient instance.

    Returns:
        List of (url, line_number, link_text) tuples.
    """
    results = []
    try:
        text = _read_file_content(
            filepath,
            target_type,
            repo_owner,
            repo_name_short,
            github_client,
        )
    except OSError:
        return results

    for line_num, line in enumerate(text.splitlines(), start=1):
        for match in _URL_RE.finditer(line):
            url = match.group(0).rstrip(".,;:!?)")
            results.append((url, line_num, url))

    return results


def _check_single_url(url: str) -> dict:
    """Check a single URL using the network module.

    Args:
        url: URL to check.

    Returns:
        RequestResult-like dict with status info.
    """
    result = network_check_url(url)
    return dict(result)


def _is_dead(result: dict) -> bool:
    """Determine if a check result indicates a dead link.

    Args:
        result: Result dict from _check_single_url.

    Returns:
        True if the link is dead.
    """
    status = result.get("status", "")
    if status in ("dead", "error"):
        return True
    code = result.get("status_code")
    if code is not None and code >= 400:
        return True
    return False


def parse_scan_output(json_output: str) -> list[DeadLink]:
    """Parse JSON scan output into DeadLink objects.

    Args:
        json_output: JSON string with scan results.

    Returns:
        List of DeadLink dicts.
    """
    if not json_output:
        return []
    try:
        data = json.loads(json_output)
    except (json.JSONDecodeError, TypeError):
        return []

    return [
        DeadLink(
            url=item["url"],
            source_file=item["source_file"],
            line_number=item["line_number"],
            link_text=item.get("link_text", ""),
            http_status=item.get("http_status"),
            error_type=item.get("error_type", "unknown"),
        )
        for item in data
    ]


def run_link_scan(
    doc_files: list[str],
    target: str,
    target_type: str,
    repo_owner: str = "",
    repo_name_short: str = "",
    github_client: object | None = None,
) -> list[DeadLink]:
    """Execute link scanning on documentation files.

    Extracts URLs from each file and checks them.

    Args:
        doc_files: List of documentation file paths.
        target: Repository target (for context).
        target_type: "url" or "local".
        repo_owner: Repository owner (for URL targets).
        repo_name_short: Repository name (for URL targets).
        github_client: Optional GitHubContentsClient instance.

    Returns:
        List of dead links found.
    """
    if not doc_files:
        return []

    dead_links: list[DeadLink] = []
    seen_urls: set[str] = set()

    for filepath in doc_files:
        urls = _extract_urls_from_file(
            filepath,
            target_type,
            repo_owner,
            repo_name_short,
            github_client,
        )
        for url, line_num, link_text in urls:
            if url in seen_urls:
                continue
            seen_urls.add(url)

            result = _check_single_url(url)
            if _is_dead(result):
                dead_links.append(
                    DeadLink(
                        url=url,
                        source_file=filepath,
                        line_number=line_num,
                        link_text=link_text,
                        http_status=result.get("status_code"),
                        error_type=result.get("error_type", "http_error"),
                    )
                )

    return dead_links


def n1_scan(state: PipelineState) -> PipelineState:
    """N1 node: Scan for dead links (Lu-Tze).

    Wraps run_link_scan and updates pipeline state.

    Args:
        state: Current pipeline state.

    Returns:
        Updated PipelineState with dead_links populated.
    """
    doc_files = state.get("doc_files", [])
    target = state.get("target", "")
    target_type = state.get("target_type", "local")
    repo_owner = state.get("repo_owner", "")
    repo_name_short = state.get("repo_name_short", "")

    try:
        dead_links = run_link_scan(
            doc_files,
            target,
            target_type,
            repo_owner=repo_owner,
            repo_name_short=repo_name_short,
        )
        state["dead_links"] = dead_links
    except Exception as exc:
        state["errors"] = state.get("errors", []) + [f"Scan error: {exc}"]
        state["dead_links"] = state.get("dead_links", [])

    state["scan_complete"] = True
    return state
