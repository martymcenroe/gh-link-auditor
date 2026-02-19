"""Data structures for Slant scoring engine.

TypedDict definitions for signal scores, scoring breakdowns,
verdicts, and forensic report entries.

See LLD #21 §2.3 for specification.
"""

from __future__ import annotations

from typing import List, Optional, TypedDict


class SignalScore(TypedDict):
    """Individual signal score with metadata."""

    signal_name: str
    raw_score: float
    weighted_score: float
    weight: int


class ScoringBreakdown(TypedDict):
    """All 5 signal scores for a candidate (weighted values)."""

    redirect: float
    title_match: float
    content_similarity: float
    url_similarity: float
    domain_match: float


class Verdict(TypedDict):
    """Verdict for a single dead link."""

    dead_url: str
    verdict: str
    confidence: int
    replacement_url: Optional[str]
    scoring_breakdown: ScoringBreakdown
    human_decision: Optional[str]
    decided_at: Optional[str]


class VerdictsFile(TypedDict):
    """Root structure of verdicts.json."""

    generated_at: str
    source_report: str
    verdicts: List[Verdict]


class SignalWeights(TypedDict):
    """Configurable signal weights."""

    redirect: int
    title: int
    content: int
    url_path: int
    domain: int


class CandidateEntry(TypedDict):
    """Candidate replacement URL from forensic report."""

    url: str
    source: str


class ForensicReportEntry(TypedDict):
    """Single dead link from Cheery's forensic report (input format)."""

    dead_url: str
    archived_url: str
    archived_title: str
    archived_content: str
    investigation_method: str
    candidates: List[CandidateEntry]
