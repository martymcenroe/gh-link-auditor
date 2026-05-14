"""Stage 2 — bulk HEAD probe of every unique URL across the corpus (#218).

Uses the existing `network.check_url` for consistency with N1's behavior
(HEAD + 4xx-GET-fallback + stealth where eligible).
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from gh_link_auditor.bulk_scan.config import LIVENESS_WORKER_COUNT
from gh_link_auditor.network import check_url as network_check_url
from gh_link_auditor.network import create_request_config

logger = logging.getLogger(__name__)


def _probe_one(url: str) -> tuple[str, dict]:
    """HEAD/GET probe one URL with the same config as N1 (#190 stealth fallback enabled)."""
    config = create_request_config()
    config["allow_headless"] = True  # type: ignore[typeddict-unknown-key]
    try:
        result = network_check_url(url, request_config=config)
        return url, dict(result)
    except Exception as e:
        logger.debug("probe failed: %s :: %s", url, e)
        return url, {"status": "error", "error": str(e)}


def is_dead_result(result: dict) -> bool:
    status = result.get("status", "")
    if status in ("dead", "error"):
        return True
    code = result.get("status_code")
    if code is not None and code >= 400:
        return True
    return False


def check_urls_bulk(
    urls: list[str],
    workers: int = LIVENESS_WORKER_COUNT,
) -> dict[str, dict]:
    """Probe each URL in `urls` concurrently. Returns dict[url -> result]."""
    out: dict[str, dict] = {}
    if not urls:
        return out
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_probe_one, u): u for u in urls}
        for fut in as_completed(futures):
            url, result = fut.result()
            out[url] = result
    return out
