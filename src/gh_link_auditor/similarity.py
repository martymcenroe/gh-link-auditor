"""Text similarity scoring utilities for dead link investigation.

Uses difflib.SequenceMatcher (stdlib) per LLD #20 §2.7.
No external dependencies required.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher


def normalize_text(text: str) -> str:
    """Normalize text for comparison.

    Lowercases, strips leading/trailing whitespace, and collapses
    internal whitespace (spaces, tabs, newlines) to single spaces.

    Args:
        text: Raw text string.

    Returns:
        Normalized text.
    """
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def compute_similarity(text_a: str, text_b: str) -> float:
    """Compute text similarity score (0.0–1.0) using SequenceMatcher.

    Both inputs are normalized before comparison.

    Args:
        text_a: First text.
        text_b: Second text.

    Returns:
        Similarity ratio between 0.0 and 1.0.
    """
    a = normalize_text(text_a)
    b = normalize_text(text_b)
    return SequenceMatcher(None, a, b).ratio()
