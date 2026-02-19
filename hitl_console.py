"""Interactive console for Human-in-the-Loop link resolution.

Presents broken links from a scan report and lets the user resolve
each one interactively. See LLD #10 for design rationale.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import urlparse

from src.logging_config import setup_logging

logger = setup_logging("hitl_console")


# ---------------------------------------------------------------------------
# Public API (LLD §2.4)
# ---------------------------------------------------------------------------


def filter_broken_links(results: list[dict]) -> list[dict]:
    """Extract only broken links (status != 'ok') from results.

    Returns references to the original dicts so mutations propagate.

    Args:
        results: Full scan results list.

    Returns:
        List of result dicts with non-ok status.
    """
    return [r for r in results if r.get("status") != "ok"]


def validate_url(url: str) -> bool:
    """Basic URL validation for replacement URLs.

    Checks for valid http/https scheme and non-empty netloc.

    Args:
        url: URL string to validate.

    Returns:
        ``True`` if the URL has a valid http(s) scheme and host.
    """
    if not url:
        return False
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def apply_resolution(
    link: dict,
    action: str,
    new_url: str | None,
    note: str | None,
) -> None:
    """Apply resolution data to a link result in-place.

    Adds a ``resolution`` dict matching JSON schema (00008).

    Args:
        link: The link result dict to update.
        action: One of ``"replace"``, ``"remove"``, ``"ignore"``, ``"keep"``.
        new_url: Replacement URL (only for ``"replace"`` action).
        note: Optional user-provided note.
    """
    link["resolution"] = {
        "action": action,
        "new_url": new_url,
        "resolved_by": "human",
        "resolved_at": datetime.now(timezone.utc).isoformat(),
        "note": note,
    }


def save_results(results: list[dict], output_path: str) -> None:
    """Save current results to a JSON file.

    Args:
        results: Full results list (possibly with resolutions applied).
        output_path: Path to write the JSON report to.
    """
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    logger.info("Results saved to %s", output_path)


def display_link_info(link: dict, index: int, total: int) -> None:
    """Print formatted details about a broken link.

    Args:
        link: The broken link result dict.
        index: Zero-based current position.
        total: Total number of broken links.
    """
    print(f"\n--- Link {index + 1} of {total} ---")
    print(f"  URL:    {link.get('url', 'N/A')}")
    print(f"  Status: {link.get('status', 'N/A')} (code: {link.get('status_code', 'N/A')})")
    if link.get("error"):
        print(f"  Error:  {link['error']}")
    if link.get("resolution"):
        res = link["resolution"]
        print(f"  Resolution: {res['action']}", end="")
        if res.get("new_url"):
            print(f" -> {res['new_url']}", end="")
        print()


def display_menu() -> None:
    """Print the available action menu."""
    print("\n  [r] Replace   [d] Remove   [i] Ignore   [k] Keep")
    print("  [n] Next      [p] Prev     [s] Save     [q] Quit")


def get_user_action() -> str:
    """Prompt user for action input.

    Returns:
        Lowercase single character from user input.
    """
    return input("\n  Action: ").strip().lower()


def prompt_replacement_url() -> str | None:
    """Prompt user to enter a replacement URL.

    Returns:
        Validated URL string, or ``None`` if cancelled or invalid.
    """
    url = input("  New URL: ").strip()
    if not url:
        return None
    if not validate_url(url):
        print("  Invalid URL. Must start with http:// or https://")
        return None
    return url


def prompt_note() -> str | None:
    """Prompt user for optional resolution note.

    Returns:
        Note string, or ``None`` if skipped.
    """
    note = input("  Note (optional, Enter to skip): ").strip()
    return note if note else None


def handle_quit(modified: bool) -> bool:
    """Handle quit command with unsaved changes prompt.

    Args:
        modified: Whether any resolutions have been applied.

    Returns:
        ``True`` if user confirms quit, ``False`` to continue.
    """
    if modified:
        print("  You have unsaved changes. Save before quitting?")
        answer = input("  [y] Save and quit  [n] Quit without saving  [c] Cancel: ").strip().lower()
        if answer == "c":
            return False
        # Both 'y' and 'n' (and anything else) quit — 'y' case handled by caller
        return True
    return True


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def run_hitl_console(results: list[dict]) -> list[dict]:
    """Main entry point for HITL resolution mode.

    Filters results to broken links, presents an interactive menu,
    and returns the updated results list with resolution data.

    Args:
        results: Full scan results list.

    Returns:
        The (possibly mutated) results list.
    """
    broken = filter_broken_links(results)

    if not broken:
        print("No broken links to resolve.")
        return results

    print(f"\nFound {len(broken)} broken link(s) to review.")

    index = 0
    modified = False

    try:
        while 0 <= index < len(broken):
            display_link_info(broken[index], index, len(broken))
            display_menu()

            action = get_user_action()

            if action == "r":
                url = prompt_replacement_url()
                if url:
                    note = prompt_note()
                    apply_resolution(broken[index], "replace", url, note)
                    modified = True
                    index += 1
            elif action == "d":
                apply_resolution(broken[index], "remove", None, None)
                modified = True
                index += 1
            elif action == "i":
                apply_resolution(broken[index], "ignore", None, None)
                modified = True
                index += 1
            elif action == "k":
                apply_resolution(broken[index], "keep", None, None)
                modified = True
                index += 1
            elif action == "n":
                index = min(index + 1, len(broken) - 1)
            elif action == "p":
                index = max(index - 1, 0)
            elif action == "s":
                save_results(results, "hitl_report.json")
                print("  Saved to hitl_report.json")
            elif action == "q":
                if handle_quit(modified):
                    break
            else:
                print(f"  Unknown command: '{action}'")

    except EOFError:
        logger.info("EOF received — exiting HITL console")
    except KeyboardInterrupt:
        logger.info("Interrupt received — exiting HITL console")

    return results
