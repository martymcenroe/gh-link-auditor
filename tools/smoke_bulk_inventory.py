"""Smoke test for the rate-limited bulk-scan inventory client (#224)."""

import os

from gh_link_auditor.bulk_scan.inventory import (
    build_api_client,
    build_raw_client,
    inventory_repo,
)


def main() -> None:
    api = build_api_client(os.environ.get("GITHUB_TOKEN"))
    raw = build_raw_client()
    try:
        result = inventory_repo("pallets/click", api, raw)
        print(f"docs: {len(result['doc_files'])}, urls: {len(result['urls'])}")
        print(f"requests: {api.total_requests}, sleep_s: {api.total_sleep_s:.1f}")
        print(f"429s: {api.total_429s}, secondary: {api.total_secondary_limits}")
        print(f"quota remaining: {api._remaining}")
    finally:
        api.close()
        raw.close()


if __name__ == "__main__":
    main()
