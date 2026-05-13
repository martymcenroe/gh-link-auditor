"""Hostile-comment classifier for maintainer responses on PRs.

Tight, conservative phrase list. Bias: false negatives over false positives —
mis-blacklisting a friendly maintainer is worse than missing a hostile one.

See LLD-178 for the design and why the list is what it is.
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

MAINTAINER_ASSOCIATIONS: frozenset[str] = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})


def is_hostile_text(body: str | None) -> bool:
    """True if any hostile phrase appears in the comment body (case-insensitive)."""
    if not body:
        return False
    lower = body.lower()
    return any(phrase in lower for phrase in HOSTILE_PHRASES)


def is_maintainer_comment(author_association: str | None) -> bool:
    """True if the commenter has push access (OWNER, MEMBER, or COLLABORATOR)."""
    if not author_association:
        return False
    return author_association.upper() in MAINTAINER_ASSOCIATIONS
