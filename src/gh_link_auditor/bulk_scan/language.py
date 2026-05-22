"""Per-repo natural-language detection for bulk-scan (#238).

Fetches the repo's README via raw.githubusercontent.com (no GitHub API quota
cost) and classifies via langdetect. The result lives in
``bulk_scan_repos.detected_language`` and is used by Stage 3 to skip findings
from repos in languages the operator can't usefully triage.

The detection result is opportunistic: ``None`` means "unknown" (fetch failed
or text too short to classify reliably). Stage 3 treats ``None`` as
"include" — never silently drops findings from unclassified repos.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from langdetect import DetectorFactory, LangDetectException, detect

logger = logging.getLogger(__name__)

# Seed for reproducibility — langdetect is non-deterministic by default.
DetectorFactory.seed = 0

_README_VARIANTS = ("README.md", "README.rst", "README.txt", "README")
_RAW_BASE = "https://raw.githubusercontent.com"
_MIN_TEXT_LEN = 100  # langdetect is unreliable below ~100 chars
_MAX_TEXT_LEN = 5000  # cap input to keep detection fast


def _fetch_readme(repo_full_name: str, variant: str, client: httpx.Client) -> str | None:
    """Fetch one README variant from raw CDN. Returns text on 200, None otherwise."""
    url = f"{_RAW_BASE}/{repo_full_name}/HEAD/{variant}"
    try:
        r = client.get(url, follow_redirects=True, timeout=15)
        if r.status_code == 200 and r.text:
            return r.text
    except (httpx.HTTPError, OSError) as e:
        logger.debug("readme fetch failed: %s :: %s :: %s", repo_full_name, variant, e)
    return None


def detect_repo_language(repo_full_name: str, client: Any | None = None) -> str | None:
    """Try each README variant; detect language of the first one that resolves.

    Returns an ISO 639-1 code (e.g. ``en``, ``ja``) or compound code (``zh-cn``),
    or ``None`` if no README could be fetched, the text is too short, or
    langdetect can't classify.
    """
    own_client = False
    if client is None:
        client = httpx.Client(headers={"User-Agent": "gh-link-auditor-lang"}, timeout=15.0)
        own_client = True
    try:
        for variant in _README_VARIANTS:
            text = _fetch_readme(repo_full_name, variant, client)
            if text is None or len(text) < _MIN_TEXT_LEN:
                continue
            try:
                return detect(text[:_MAX_TEXT_LEN])
            except LangDetectException:
                continue
        return None
    finally:
        if own_client:
            client.close()
