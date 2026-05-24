"""Phase B preflight package — runs hard gates + scored evaluation on a
candidate before any fork (#281 umbrella).

Sub-modules:
- ``subagent`` — ``claude --print`` wrapper + ``FakeSubagent`` for tests (#287)
- ``report`` — markdown + JSON renderers + save_report helper (#286)
- Future: ``gates`` (10 hard gates) and ``scores`` (12 score components)
"""

from gh_link_auditor.preflight.report import (
    GateResult,
    PreflightReport,
    PreflightVerdict,
    ScoreComponent,
    render_json,
    render_markdown,
    save_report,
)
from gh_link_auditor.preflight.subagent import (
    ANTI_AI_FALLBACK_AVAILABLE,
    FALLBACK_USED,
    RealSubagent,
    Subagent,
    SubagentVerdict,
    anti_ai_keyword_fallback,
)

__all__ = [
    "ANTI_AI_FALLBACK_AVAILABLE",
    "FALLBACK_USED",
    "GateResult",
    "PreflightReport",
    "PreflightVerdict",
    "RealSubagent",
    "ScoreComponent",
    "Subagent",
    "SubagentVerdict",
    "anti_ai_keyword_fallback",
    "render_json",
    "render_markdown",
    "save_report",
]
