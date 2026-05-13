"""Maintainer-comment classifiers for hostile and anti-AI signals.

Tight, conservative phrase lists. Bias: false negatives over false positives —
mis-blacklisting a friendly maintainer is worse than missing one.

See LLD-178 (hostile) and #200 (anti-AI) for the design.
"""

from __future__ import annotations

HOSTILE_PHRASES: tuple[str, ...] = (
    "fuck off",
    "fuck you",
    "go fuck yourself",
    "shut the fuck up",
    "spammer",
    "harassment",
    "stop opening prs",
    "stop opening pull requests",
    "stop submitting prs",
    "stop submitting pull requests",
    "no more prs",
    "stop with the prs",
    "blocked you",
    "block this account",
)

ANTI_AI_PHRASES: tuple[str, ...] = (
    # Seed list from real maintainer rejections (pallets/flask #6019, davidism:
    # "Happy to update this, but please do not use genAI to generate or submit a PR.")
    "do not use genai",
    "do not use ai",
    "don't use genai",
    "don't use ai",
    "please don't use ai",
    "please do not use ai",
    "no ai-generated",
    "no ai generated",
    "ai-generated pr",
    "ai generated pr",
    "no llm",
    "don't use llm",
    "no bot pr",
    "no bot prs",
    "no automated pr",
    "no automated prs",
    "don't automate",
    "do not automate",
    "no ai contributions",
    "no ai-assisted",
)

MAINTAINER_ASSOCIATIONS: frozenset[str] = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})


def is_hostile_text(body: str | None) -> bool:
    """True if any hostile phrase appears in the comment body (case-insensitive)."""
    if not body:
        return False
    lower = body.lower()
    return any(phrase in lower for phrase in HOSTILE_PHRASES)


def is_anti_ai_text(body: str | None) -> bool:
    """True if any anti-AI phrase appears in the comment body (case-insensitive).

    Polite-but-firm rejection class. Distinct from hostile (#178) because the
    text is typically not abusive — the signal is "this maintainer doesn't
    want AI-generated PRs", not "this maintainer is rude". See #200.
    """
    if not body:
        return False
    lower = body.lower()
    return any(phrase in lower for phrase in ANTI_AI_PHRASES)


def is_maintainer_comment(author_association: str | None) -> bool:
    """True if the commenter has push access (OWNER, MEMBER, or COLLABORATOR)."""
    if not author_association:
        return False
    return author_association.upper() in MAINTAINER_ASSOCIATIONS
