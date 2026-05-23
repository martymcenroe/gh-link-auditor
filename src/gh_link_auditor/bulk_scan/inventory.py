"""Stage 1 — per-repo doc inventory via Git Trees API + raw.githubusercontent (#218).

One API call per repo to list the tree (recursive), then content via raw CDN
(no REST API rate-limit hit). URL extraction reuses the regex from N1.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote, urlparse

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
    """Strip trailing punctuation; cut at first unmatched closing paren.

    Markdown like ``[name](url)'s text`` makes the URL regex capture
    ``url)'s`` — the trailing ``s`` is a word-char so the trail-chars
    strip can't reach the ``)``. We detect unbalanced parens and cut
    at the first unmatched ``)``; anything after is markdown spillover.

    Balanced parens are preserved (Wikipedia ``Foo_(bar)`` style).
    """
    while raw and raw[-1] in _TRAIL_CHARS:
        raw = raw[:-1]

    closes = raw.count(")")
    opens = raw.count("(")
    if closes > opens:
        depth = 0
        cut_at: int | None = None
        for i, ch in enumerate(raw):
            if ch == "(":
                depth += 1
            elif ch == ")":
                if depth == 0:
                    cut_at = i
                    break
                depth -= 1
        if cut_at is not None:
            raw = raw[:cut_at]

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
    """True if the URL is worth probing. False = skip (already-known-fp).

    Malformed URLs (``urlparse`` raises ValueError on bracketed-bare,
    NFKC-bad netlocs, embedded newlines, etc.) are silently skipped here
    rather than allowed to crash the whole repo's inventory (#227).
    """
    try:
        urlparse(url)
    except ValueError:
        return False
    if is_placeholder_url(url):
        return False
    if is_api_test_endpoint(url):
        return False
    if is_always_alive_domain(url):
        return False
    return True


def _is_safe_doc_path(path: str) -> bool:
    """True if path can be safely composed into a URL (#251).

    Git permits almost any byte in a filename except ``/`` and ``\\0``,
    including C0 control chars (``\\n``, ``\\r``, ``\\t``, ``\\x00`` …).
    RFC 3986 forbids these in URLs, and ``httpx.URL`` rejects them with
    ``InvalidURL`` — which previously aborted the entire repo's inventory.
    Real doc files do not have these in their names; dropping the path
    is the correct behavior.
    """
    return bool(path) and all(ord(c) >= 0x20 for c in path)


class RepoRenamed(Exception):
    """Signal from Stage 1 inventory that the repo was renamed on GitHub (#250).

    Carries the new ``full_name`` so callers can update DB state and retry
    inventory under the new name in a single bounded retry.
    """

    def __init__(self, new_full_name: str) -> None:
        self.new_full_name = new_full_name
        super().__init__(f"repo renamed to {new_full_name}")


def _resolve_renamed_repo(client: Any, redirect_location: str) -> str | None:
    """Given a 301 ``Location`` URL of the form ``.../repositories/{id}/...``,
    return the repo's current ``full_name`` or ``None`` if it can't be resolved.

    Failure modes (all return ``None``):

    * No ``/repositories/{id}`` pattern in the URL.
    * Lookup ``/repositories/{id}`` returns non-2xx.
    * Response body lacks ``full_name``.
    * Network / transport error.

    The function is deliberately permissive — any failure here should fall
    through to the normal ``raise_for_status`` error path so we don't make
    things worse than the pre-existing failure mode.
    """
    m = re.search(r"/repositories/(\d+)", redirect_location)
    if not m:
        return None
    repo_id = m.group(1)
    try:
        r = client.get(f"{_GH_API}/repositories/{repo_id}")
        r.raise_for_status()
        full_name = r.json().get("full_name")
        return full_name if isinstance(full_name, str) and full_name else None
    except Exception:
        return None


def _list_doc_files(client: Any, full_name: str) -> list[str]:
    """One Git Trees API call → all doc files in the repo.

    ``client`` may be either an ``httpx.Client`` or a
    :class:`GitHubRateLimitedClient` — both expose ``.get(url, params=...)``.

    Per #251, paths containing C0 control characters are dropped silently —
    they cannot survive in URLs and dropping them keeps the rest of the
    repo's docs reachable.

    Per #250, a 301 redirect with a resolvable ``Location`` header signals
    that the repo was renamed: ``RepoRenamed`` is raised carrying the new
    ``full_name``. The caller is expected to update its state and retry
    once with the new name. Unresolvable 301s and all other non-2xx
    statuses propagate via ``raise_for_status`` as before.
    """
    r = client.get(f"{_GH_API}/repos/{full_name}/git/trees/HEAD", params={"recursive": "1"})
    if r.status_code == 301:
        location = r.headers.get("Location") or r.headers.get("location")
        if location:
            new_name = _resolve_renamed_repo(client, location)
            if new_name and new_name != full_name:
                raise RepoRenamed(new_name)
    r.raise_for_status()
    tree = r.json().get("tree", [])
    docs: list[str] = []
    for entry in tree:
        if entry.get("type") != "blob":
            continue
        path = entry.get("path", "")
        if not _is_safe_doc_path(path):
            logger.debug("dropping pathological doc path: %s :: %r", full_name, path)
            continue
        if any(path.lower().endswith(ext) for ext in DOC_FILE_EXTENSIONS):
            docs.append(path)
        if len(docs) >= MAX_DOC_FILES_PER_REPO:
            break
    return docs


def _fetch_raw(client: httpx.Client, full_name: str, path: str) -> str | None:
    """Fetch via raw CDN — does NOT count against the REST API rate limit.

    Per #251, the path component is URL-encoded so spaces, ``#``, ``?`` and
    other reserved characters don't crash URL parsing. ``safe='/'`` keeps
    directory separators literal so the path structure survives encoding.
    """
    url = f"{_RAW_BASE}/{full_name}/HEAD/{quote(path, safe='/')}"
    try:
        r = client.get(url, follow_redirects=True, timeout=20)
        if r.status_code == 200:
            return r.text
    except (httpx.HTTPError, OSError):
        pass
    return None


def inventory_repo(
    full_name: str,
    api_client: Any,  # GitHubRateLimitedClient or httpx.Client (tests)
    raw_client: httpx.Client,
) -> dict[str, Any]:
    """Walk one repo. Returns ``{"doc_files": [...], "urls": [...], "renamed_from": ..., "current_full_name": ...}``.

    Raises on tree-list failure (so the caller can mark the repo errored).
    Per-file fetch failures are silently skipped (logged at debug).

    Per #250, if the trees API responds with a 301 redirect pointing at a
    new repo location, ``_list_doc_files`` raises ``RepoRenamed``. We
    perform exactly one retry under the new name. If the retry also
    redirects, the exception propagates — multi-rename chains are out of
    scope and not worth a loop.

    Result keys:

    * ``doc_files`` — list of doc-file paths under the (possibly renamed) repo
    * ``urls`` — extracted URLs as ``(url, source_file, line_number)`` tuples
    * ``renamed_from`` — the original ``full_name`` argument iff a rename was
      followed; otherwise ``None``
    * ``current_full_name`` — the name under which inventory actually
      succeeded (= the original name when no rename happened)
    """
    renamed_from: str | None = None
    try:
        docs = _list_doc_files(api_client, full_name)
    except RepoRenamed as e:
        renamed_from = full_name
        full_name = e.new_full_name
        # One-shot retry under the new name.
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
    return {
        "doc_files": docs,
        "urls": urls,
        "renamed_from": renamed_from,
        "current_full_name": full_name,
    }


def build_api_client(token: str | None = None) -> Any:
    """Build the rate-limited GitHub REST client used by the bulk scan (#224).

    Returns a :class:`GitHubRateLimitedClient` (compatible with the prior
    ``httpx.Client`` interface — supports ``.get(url, params=...)`` and
    ``.close()`` / context-manager use).

    If ``token`` is not provided AND ``GITHUB_TOKEN`` is not in env, falls
    back to ``gh auth token`` via :func:`resolve_github_token`. This is
    critical for the bulk run — without auth, GitHub's anonymous rate limit
    is **60 req/hr**, which trips the secondary rate limit immediately on
    a 7500-repo sweep. The first 2026-05-14 fire failed for exactly this
    reason: ``GITHUB_TOKEN`` was unset and the client was anonymous.
    """
    from gh_link_auditor.auth import resolve_github_token
    from gh_link_auditor.bulk_scan.gh_client import GitHubRateLimitedClient

    if not token:
        try:
            token = resolve_github_token()
        except Exception:
            token = None
    return GitHubRateLimitedClient(token=token)


def build_raw_client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": "gh-link-auditor-bulk"},
        timeout=20.0,
        follow_redirects=True,
    )
