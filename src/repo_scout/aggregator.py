"""Aggregator — Deduplicate and merge repository records.

See LLD #3 §2.4 for aggregator specification.
"""

from __future__ import annotations

from repo_scout.models import RepositoryRecord


def merge_sources(
    existing: RepositoryRecord,
    new: RepositoryRecord,
) -> RepositoryRecord:
    """Merge source information when same repo found multiple times.

    Args:
        existing: The existing record to update.
        new: The new record to merge in.

    Returns:
        Merged RepositoryRecord.
    """
    merged = dict(existing)

    # Combine sources
    all_sources = list(set(existing["sources"] + new["sources"]))
    merged["sources"] = all_sources

    # Keep highest star count
    if new.get("stars") is not None:
        if existing.get("stars") is None or new["stars"] > existing["stars"]:
            merged["stars"] = new["stars"]

    # Keep description if missing
    if not existing.get("description") and new.get("description"):
        merged["description"] = new["description"]

    # Merge metadata
    merged_meta = dict(existing.get("metadata", {}))
    for key, value in new.get("metadata", {}).items():
        if key not in merged_meta:
            merged_meta[key] = value
    merged["metadata"] = merged_meta

    return merged  # type: ignore[return-value]


def deduplicate_repos(
    repos: list[RepositoryRecord],
) -> list[RepositoryRecord]:
    """Merge duplicate repos, combining their source metadata.

    Args:
        repos: List of potentially duplicate RepositoryRecords.

    Returns:
        Deduplicated list.
    """
    by_name: dict[str, RepositoryRecord] = {}

    for repo in repos:
        full_name = repo["full_name"].lower()
        if full_name in by_name:
            by_name[full_name] = merge_sources(by_name[full_name], repo)
        else:
            by_name[full_name] = repo

    return list(by_name.values())


def sort_by_relevance(
    repos: list[RepositoryRecord],
) -> list[RepositoryRecord]:
    """Sort repos by number of sources (desc) then star count (desc).

    Args:
        repos: List of RepositoryRecords.

    Returns:
        Sorted list.
    """
    return sorted(
        repos,
        key=lambda r: (len(r.get("sources", [])), r.get("stars") or 0),
        reverse=True,
    )
