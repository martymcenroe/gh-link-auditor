"""Casual-register PR title and body generation for pipeline fixes.

Output deliberately avoids AI-tell pattern signals: no conventional-commits
prefix, no bot self-attribution, no markdown bold, no em-dashes, no Unicode
arrows, no polished verification sentences.

See Issue #209 for spec and Issue #85 for the original (now-replaced) design.
"""

from __future__ import annotations

from gh_link_auditor.pipeline.state import FixPatch, Verdict


def generate_pr_title_from_fixes(fixes: list[FixPatch]) -> str:
    """Generate a lowercase, no-prefix PR title."""
    if not fixes:
        return "fix broken docs links"
    if len(fixes) == 1:
        return "fix broken docs link"
    return f"fix {len(fixes)} broken docs links"


def _find_verdict_for_fix(fix: FixPatch, verdicts: list[Verdict]) -> Verdict | None:
    """Look up the verdict whose dead_link matches this fix's URL and source file."""
    for v in verdicts:
        dl = v.get("dead_link", {})
        if dl.get("url") == fix["original_url"] and dl.get("source_file") == fix["source_file"]:
            return v
    return None


def generate_pr_body_from_fixes(
    fixes: list[FixPatch],
    verdicts: list[Verdict] | None = None,
) -> str:
    """Generate a casual PR body. Lowercase, fragmented, no markdown formatting."""
    if verdicts is None:
        verdicts = []

    if not fixes:
        return "ran a check but found nothing worth fixing"

    if len(fixes) == 1:
        fix = fixes[0]
        return f"{fix['original_url']} is dead\n\nthink this is the one you want: {fix['replacement_url']}"

    lines: list[str] = [f"found {len(fixes)} dead links in the docs", ""]
    for fix in fixes:
        verdict = _find_verdict_for_fix(fix, verdicts)
        dl = verdict.get("dead_link", {}) if verdict else {}
        line_number = dl.get("line_number")
        loc = fix["source_file"]
        if line_number:
            loc = f"{loc} line {line_number}"
        lines.append(f"{loc}: {fix['original_url']} -> {fix['replacement_url']}")
    return "\n".join(lines)
