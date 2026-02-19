"""CLI entry point for Repo Scout.

See LLD #3 §2.4 for CLI specification.
Deviation: uses argparse instead of typer to match codebase conventions.
"""

from __future__ import annotations

import argparse
import os
import sys

from repo_scout.aggregator import deduplicate_repos, sort_by_relevance
from repo_scout.awesome_parser import parse_awesome_list
from repo_scout.github_client import GitHubClient
from repo_scout.llm_brainstormer import suggest_repos
from repo_scout.models import RepositoryRecord
from repo_scout.output_writer import write_output
from repo_scout.star_walker import walk_starred_repos


def print_progress(message: str, current: int, total: int) -> None:
    """Display progress indicator during operation.

    Args:
        message: Progress message.
        current: Current item number.
        total: Total item count.
    """
    print(f"[{current}/{total}] {message}", file=sys.stderr)


def print_statistics(repos: list[RepositoryRecord]) -> None:
    """Print final discovery statistics.

    Args:
        repos: Final deduplicated repository list.
    """
    total = len(repos)
    by_source: dict[str, int] = {}
    for repo in repos:
        for source in repo["sources"]:
            by_source[source] = by_source.get(source, 0) + 1

    print("\nRepo Scout Results:", file=sys.stderr)
    print(f"  Total unique repos: {total}", file=sys.stderr)
    for source, count in sorted(by_source.items()):
        print(f"  From {source}: {count}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser.

    Returns:
        Configured ArgumentParser.
    """
    parser = argparse.ArgumentParser(
        prog="repo-scout",
        description="Discover GitHub repositories for dead link auditing",
    )
    parser.add_argument(
        "--awesome-lists", nargs="*", default=[],
        help="URLs of Awesome list repositories to parse",
    )
    parser.add_argument(
        "--root-users", nargs="*", default=[],
        help="GitHub usernames for star walking",
    )
    parser.add_argument(
        "--keywords", nargs="*", default=[],
        help="Keywords for LLM suggestions",
    )
    parser.add_argument(
        "--star-depth", type=int, default=2,
        help="Max depth for star walking (default: 2)",
    )
    parser.add_argument(
        "--output", default="targets.json",
        help="Output file path (default: targets.json)",
    )
    parser.add_argument(
        "--format", choices=["json", "jsonl", "txt"], default="json",
        help="Output format (default: json)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Main entry point for Repo Scout CLI.

    Args:
        argv: Command line arguments.

    Returns:
        Exit code.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN", "")
    client = GitHubClient(token=token)
    all_repos: list[RepositoryRecord] = []

    try:
        # Source 1: Awesome lists
        for i, url in enumerate(args.awesome_lists):
            print_progress(f"Parsing Awesome list: {url}", i + 1, len(args.awesome_lists))
            repos = parse_awesome_list(url)
            all_repos.extend(repos)

        # Source 2: Star walking
        for i, user in enumerate(args.root_users):
            print_progress(f"Walking stars for: {user}", i + 1, len(args.root_users))
            repos = walk_starred_repos(user, client, max_depth=args.star_depth)
            all_repos.extend(repos)

        # Source 3: LLM suggestions (disabled without LLM response)
        if args.keywords:
            existing = [r["full_name"] for r in all_repos]
            repos = suggest_repos(args.keywords, existing)
            all_repos.extend(repos)

        # Deduplicate and sort
        unique = deduplicate_repos(all_repos)
        sorted_repos = sort_by_relevance(unique)

        # Write output
        count = write_output(sorted_repos, args.output, fmt=args.format)
        print_statistics(sorted_repos)
        print(f"\nWrote {count} repos to {args.output}", file=sys.stderr)

    except Exception:
        import traceback

        traceback.print_exc()
        return 1
    finally:
        client.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
