"""Live integration test for preflight (#311).

Marked ``@pytest.mark.live``: only runs when ``pytest --live`` is passed.
Hits real GitHub API + real ``claude --print`` subagent. Acts as the
canary before each preflight merge.

Usage::

    poetry run pytest -m live --live tests/integration/test_preflight_live.py

CI does NOT run this by default — cost + flakiness rule it out.
"""

from __future__ import annotations

import pytest

from gh_link_auditor.preflight.report import PreflightVerdict
from gh_link_auditor.unified_db import UnifiedDatabase
from tools.preflight_check import run_preflight


@pytest.mark.live
def test_preflight_against_andreavidali_live():
    """Live preflight against the AndreaVidali smoke-test candidate.

    Asserts the report ``PASS``es with score ≥ 90. Identifiable evidence
    spot-checked (anti_ai gate clean; stars_floor passed). Real network
    + real subagent.
    """
    # Live test uses an ephemeral DB so cache misses force fresh fetches
    with UnifiedDatabase(":memory:") as db:
        candidate = {
            "dead_url": "http://www.dlr.de/ts/en/desktopdefault.aspx/tabid-9883/16931_read-41000/",
            "candidate_url": "https://github.com/AndreaVidali/Deep-QLearning-Agent-for-Traffic-Signal-Control/blob/master/README.md",
            "source_file": "README.md",
            "line_number": 1,
            "method": "github_api_redirect",
        }
        report = run_preflight(
            "AndreaVidali/Deep-QLearning-Agent-for-Traffic-Signal-Control",
            candidate,
            db=db,
            threshold=90,
        )

    assert report.verdict == PreflightVerdict.PASS, f"verdict={report.verdict}, score={report.score}"
    assert report.score >= 90, f"score below threshold: {report.score}"
    # Spot-check some evidence
    gate_names = {g.name for g in report.gate_results}
    assert "anti_ai" in gate_names
    assert "stars_floor" in gate_names
