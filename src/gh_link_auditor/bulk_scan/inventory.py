"""Stage 1 — per-repo doc inventory via Git Trees API + raw.githubusercontent (#218).

One API call per repo to list the tree (recursive), then content via raw CDN
(no REST API rate-limit hit). URL extraction reuses the regex from N1.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from gh_link_auditor.bulk_scan.config import (
    DOC_FILE_EXTENSIONS,
    MAX_DOC_FILES_PER_REPO,
    MAX_URLS_PER_REPO,
)
from gh_link_auditor.false_positives import (
    is_always_alive_domain,
    is_api_test_endpoint,
    is_placeholder_url,
)

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://[^\s>\"\]`]+")
_FENCED_RE = re.compile(r"^(\s{0,3})(```+|~~~+)")
_INDENTED_CODE_RE = re.compile(r"^(?: {4,}|\t)")
_TRAIL_CHARS = set(".,;:!?'\"`")

_GH_API = "https://api.github.com"
_RAW_BASE = "https://raw.githubusercontent.com"


def _clean_url_tail(raw: str) -> str:
    """Strip trailing punctuation; preserve balanced parens (Wikipedia case)."""
    while raw and raw[-1] in _TRAIL_CHARS:
        raw = raw[:-1]
    while raw and raw[-1] == ")":
        opens = raw.count("(")
        closes = raw.count(")")
        if closes > opens:
            raw = raw[:-1]
        else:
            break
    while raw and raw[-1] in _TRAIL_CHARS:
        raw = raw[:-1]
    return raw


def extract_urls_from_text(text: str) -> list[tuple[str, int]]:
    """Pull (url, line_number) pairs out of doc-file text. Skips fenced code."""
    out: list[tuple[str, int]] = []
    in_fenced_block = False
    fence_marker = ""
    for line_num, line in enumerate(text.splitlines(), start=1):
        m = _FENCED_RE.match(line)
        if m:
            marker = m.group(2)[0]
            mlen = len(m.group(2))
            if not in_fenced_block:
                in_fenced_block = True
                fence_marker = marker * mlen
            elif marker == fence_marker[0] and mlen >= len(fence_marker):
                in_fenced_block = False
                fence_marker = ""
            continue
        if in_fenced_block:
            continue
        if _INDENTED_CODE_RE.match(line):
            continue
        for match in _URL_RE.finditer(line):
            url = _clean_url_tail(match.group(0))
            if url:
                out.append((url, line_num))
    return out


def filter_url(url: str) -> bool:
    """True if the URL is worth probing. False = skip (already-known-fp)."""
    if is_placeholder_url(url):
        return False
    if is_api_test_endpoint(url):
        return False
    if is_always_alive_domain(url):
        return False
    return True


def _list_doc_files(client: httpx.Client, full_name: str) -> list[str]:
    """One Git Trees API call → all doc files in the repo."""
    r = client.get(f"{_GH_API}/repos/{full_name}/git/trees/HEAD", params={"recursive": "1"})
    r.raise_for_status()
    tree = r.json().get("tree", [])
    docs: list[str] = []
    for entry in tree:
        if entry.get("type") != "blob":
            continue
        path = entry.get("path", "")
        if any(path.lower().endswith(ext) for ext in DOC_FILE_EXTENSIONS):
            docs.append(path)
        if len(docs) >= MAX_DOC_FILES_PER_REPO:
            break
    return docs


def _fetch_raw(client: httpx.Client, full_name: str, path: str) -> str | None:
    """Fetch via raw CDN — does NOT count against the REST API rate limit."""
    url = f"{_RAW_BASE}/{full_name}/HEAD/{path}"
    try:
        r = client.get(url, follow_redirects=True, timeout=20)
        if r.status_code == 200:
            return r.text
    except (httpx.HTTPError, OSError):
        pass
    return None


def inventory_repo(
    full_name: str,
    api_client: httpx.Client,
    raw_client: httpx.Client,
) -> dict[str, Any]:
    """Walk one repo. Returns ``{"doc_files": [...], "urls": [(url, file, line), ...]}``.

    Raises on tree-list failure (so the caller can mark the repo errored).
    Per-file fetch failures are silently skipped (logged at debug).
    """
    docs = _list_doc_files(api_client, full_name)
    urls: list[tuple[str, str, int]] = []
    seen: set[str] = set()
    for path in docs:
        text = _fetch_raw(raw_client, full_name, path)
        if not text:
            logger.debug("raw fetch failed: %s :: %s", full_name, path)
            continue
        for url, line_num in extract_urls_from_text(text):
            if url in seen:
                continue
            if not filter_url(url):
                continue
            seen.add(url)
            urls.append((url, path, line_num))
            if len(urls) >= MAX_URLS_PER_REPO:
                break
        if len(urls) >= MAX_URLS_PER_REPO:
            break
    return {"doc_files": docs, "urls": urls}


def build_api_client(token: str | None = None) -> httpx.Client:
    headers: dict[str, str] = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "gh-link-auditor-bulk",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.Client(headers=headers, timeout=30.0)


def build_raw_client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": "gh-link-auditor-bulk"},
        timeout=20.0,
        follow_redirects=True,
    )
