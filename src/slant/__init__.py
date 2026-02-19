"""Mr. Slant — Scoring engine for dead link replacement candidates.

Evaluates candidate replacement URLs against 5 weighted signals
and produces confidence-tiered verdicts for HITL review.

See LLD #21 for specification.
"""

from __future__ import annotations

__version__ = "0.1.0"
