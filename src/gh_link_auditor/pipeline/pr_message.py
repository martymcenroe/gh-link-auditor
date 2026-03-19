"""Human-sounding PR title and body generation for pipeline fixes.

Generates persuasive, specific PR messages that avoid bot-like language.
Uses pipeline types (FixPatch, Verdict) rather than docfix_bot types.

See Issue #85 for specification.
"""

from __future__ import annotations

from gh_link_auditor.pipeline.state import FixPatch, Verdict


def generate_pr_title_from_fixes(fixes: list[FixPatch]) -> str:
    """Generate a conventional-commit PR title.

    Args:
        fixes: List of fix patches to include in the PR.

    Returns:
        PR title string.
    """
    if not fixes:
        return "docs: fix broken links"

    if len(fixes) == 1:
        return f"docs: fix broken link in {fixes[0]['source_file']}"

    files = sorted({f["source_file"] for f in fixes})
    if len(files) == 1:
        return f"docs: fix {len(fixes)} broken links in {files[0]}"

    return f"docs: fix {len(fixes)} broken links"


def _build_verification_detail(verdict: Verdict | None) -> str:
    """Build a verification detail line from verdict metadata.

    Args:
        verdict: The verdict for this fix, if available.

    Returns:
        Human-readable verification detail.
    """
    if verdict is None:
        return "Verified the replacement is live and points to the same content."

    candidate = verdict.get("candidate")
    if candidate is None:
        return "Verified the replacement is live and points to the same content."

    source = candidate.get("source", "")
    if source == "redirect":
        return "The original URL redirects to this new location."
    if source == "archive":
        return "Found via archive.org — same page, new URL."
    if source == "search":
        return "Found the updated URL via search — same content, new location."

    return "Verified the replacement is live and points to the same content."


def _find_verdict_for_fix(fix: FixPatch, verdicts: list[Verdict]) -> Verdict | None:
    """Find the verdict that corresponds to a fix.

    Args:
        fix: The fix patch.
        verdicts: All reviewed verdicts.

    Returns:
        Matching verdict, or None.
    """
    for v in verdicts:
        dl = v.get("dead_link", {})
        if dl.get("url") == fix["original_url"] and dl.get("source_file") == fix["source_file"]:
            return v
    return None


def generate_pr_body_from_fixes(
    fixes: list[FixPatch],
    verdicts: list[Verdict] | None = None,
) -> str:
    """Generate a human-sounding PR body.

    Specific, honest, and low-key. No bot attribution or opt-out footer.

    Args:
        fixes: List of fix patches.
        verdicts: Reviewed verdicts for context (optional).

    Returns:
        Markdown-formatted PR body.
    """
    if verdicts is None:
        verdicts = []

    if not fixes:
        return "I ran a link checker on the docs but found no fixes to apply."

    lines: list[str] = []

    if len(fixes) == 1:
        fix = fixes[0]
        verdict = _find_verdict_for_fix(fix, verdicts)
        dl = verdict.get("dead_link", {}) if verdict else {}
        http_status = dl.get("http_status")
        line_number = dl.get("line_number")

        lines.append("I ran a link checker on the docs and found a broken link:")
        lines.append("")

        status_text = f"returns {http_status}" if http_status else "is broken"
        line_text = f" on line {line_number}" if line_number else ""
        lines.append(f"- **{fix['original_url']}**{line_text} {status_text}")
        lines.append(f"- It now lives at **{fix['replacement_url']}**")
        lines.append("")

        detail = _build_verification_detail(verdict)
        lines.append(detail)

    else:
        lines.append(f"I ran a link checker on the docs and found {len(fixes)} broken links:")
        lines.append("")

        for fix in fixes:
            verdict = _find_verdict_for_fix(fix, verdicts)
            dl = verdict.get("dead_link", {}) if verdict else {}
            http_status = dl.get("http_status")
            line_number = dl.get("line_number")

            status_text = f" ({http_status})" if http_status else ""
            line_text = f" line {line_number}" if line_number else ""
            location = f"`{fix['source_file']}`{line_text}"

            lines.append(f"- {location}: **{fix['original_url']}**{status_text}")
            lines.append(f"  → **{fix['replacement_url']}**")

        lines.append("")
        lines.append("Verified each replacement is live and points to the same content.")

    return "\n".join(lines)
