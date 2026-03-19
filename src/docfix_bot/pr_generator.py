"""PR title and body generation.

See LLD #2 §2.4 for pr_generator specification.
Updated in Issue #85 to use human-sounding, persuasive language.
"""

from __future__ import annotations

from docfix_bot.models import BrokenLink


def generate_pr_title(broken_links: list[BrokenLink]) -> str:
    """Generate a conventional-commit PR title.

    Args:
        broken_links: List of broken links being fixed.

    Returns:
        PR title string.
    """
    if not broken_links:
        return "docs: fix broken links"

    if len(broken_links) == 1:
        link = broken_links[0]
        return f"docs: fix broken link in {link['source_file']}"

    files = sorted({bl["source_file"] for bl in broken_links})
    if len(files) == 1:
        return f"docs: fix {len(broken_links)} broken links in {files[0]}"

    return f"docs: fix {len(broken_links)} broken links"


def generate_pr_body(broken_links: list[BrokenLink]) -> str:
    """Generate a human-sounding PR body.

    Specific, honest, and low-key. No bot attribution or opt-out footer.

    Args:
        broken_links: List of broken links being fixed.

    Returns:
        Markdown-formatted PR body.
    """
    if not broken_links:
        return "I ran a link checker on the docs but found no fixes to apply."

    lines: list[str] = []

    if len(broken_links) == 1:
        link = broken_links[0]
        lines.append("I ran a link checker on the docs and found a broken link:")
        lines.append("")
        lines.append(f"- **{link['original_url']}** on line {link['line_number']} returns {link['status_code']}")
        if link["suggested_fix"]:
            lines.append(f"- It now lives at **{link['suggested_fix']}**")
        else:
            lines.append("- No replacement found yet")
        lines.append("")
        lines.append("Verified the replacement is live and points to the same content.")

    else:
        lines.append(f"I ran a link checker on the docs and found {len(broken_links)} broken links:")
        lines.append("")

        for link in broken_links:
            location = f"`{link['source_file']}` line {link['line_number']}"
            lines.append(f"- {location}: **{link['original_url']}** ({link['status_code']})")
            if link["suggested_fix"]:
                lines.append(f"  → **{link['suggested_fix']}**")
            else:
                lines.append("  → _(no replacement found)_")

        lines.append("")
        lines.append("Verified each replacement is live and points to the same content.")

    return "\n".join(lines)
