"""Subagent invocation for preflight LLM-based checks (#287).

Per the universal ``C:\\Users\\mcwiz\\Projects\\CLAUDE.md`` mandate:

    NEVER use ``@anthropic-ai/sdk`` or ask for API keys. Use ``claude --print``
    with ``CLAUDECODE=""`` env for all LLM calls. User has Max subscription.

So the runtime LLM call is a ``subprocess.run(["claude", "--print", ...])``
invocation with the Claude Code session indicator unset. The 60-second
timeout per call comes from #281's plan; on timeout we return
``UNCERTAIN`` (which escalates the whole preflight run to operator review).

The fallback path — used when the ``claude`` binary isn't on PATH (CI
without LLM access, cron-driven tool A run) — is a keyword scan against
``hostile_classifier.ANTI_AI_PHRASES``. Hits → ``UNCERTAIN`` (escalate,
never auto-pass); clean → score as ``CLEAN`` (safer side).
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from gh_link_auditor.hostile_classifier import ANTI_AI_PHRASES
from gh_link_auditor.preflight._subproc import run_utf8

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_S = 60

# Sentinel string in the fallback path's returned evidence dict.
FALLBACK_USED = "anti_ai_keyword_fallback"


class SubagentVerdict(str, Enum):
    """Verdict tokens the preflight subagent returns.

    The three-tier set is used by the anti-AI scan (gate #1, #288); the
    three-tier ``CLEAN | PARTIAL | UNRELATED`` set is used by content
    equivalence (score C5, #302) and redirect target (gate #7, #294).
    Both sets share ``CLEAN`` and ``UNCERTAIN`` for the timeout / failure
    fall-through path.
    """

    CLEAN = "clean"
    UNCERTAIN = "uncertain"
    HOSTILE = "hostile"
    PARTIAL = "partial"
    UNRELATED = "unrelated"


_VALID_TOKENS = {v.value for v in SubagentVerdict}


def _parse_verdict_token(raw: str) -> SubagentVerdict:
    """Parse the subagent's response into a verdict.

    The prompt explicitly asks for a single-token reply (no chain of
    thought). Anything outside the documented grammar is treated as
    ``UNCERTAIN`` so the operator gets to decide.
    """
    if not raw:
        return SubagentVerdict.UNCERTAIN
    token = raw.strip().lower().splitlines()[0].strip()
    if token in _VALID_TOKENS:
        return SubagentVerdict(token)
    return SubagentVerdict.UNCERTAIN


def anti_ai_keyword_fallback(text: str | None) -> SubagentVerdict:
    """Keyword pre-scan used when ``claude`` CLI is unavailable.

    Hits → ``UNCERTAIN`` (operator escalation); clean → ``CLEAN`` (safer
    default — we don't want false-positive blacklisting when there's no
    actual signal).
    """
    if not text:
        return SubagentVerdict.CLEAN
    lower = text.lower()
    for phrase in ANTI_AI_PHRASES:
        if phrase in lower:
            return SubagentVerdict.UNCERTAIN
    return SubagentVerdict.CLEAN


def ANTI_AI_FALLBACK_AVAILABLE() -> bool:  # noqa: N802 — sentinel-style helper
    """True when the keyword fallback can be used (always; no external dep)."""
    return True


class Subagent(Protocol):
    """Protocol for objects that can run a preflight subagent prompt."""

    def run(self, prompt_path: Path, context: dict[str, Any]) -> SubagentVerdict:
        """Render ``prompt_path`` with ``context`` and return a verdict."""
        ...


class RealSubagent:
    """Invokes ``claude --print`` via subprocess.

    Each ``run`` constructs the prompt by reading ``prompt_path`` and
    appending ``json.dumps(context, indent=2)`` as the operator context.
    The subagent's response is parsed against ``SubagentVerdict``.

    Failures (binary missing, non-zero exit, timeout) all map to
    ``UNCERTAIN`` so preflight escalates to operator review rather than
    silently auto-passing.
    """

    def __init__(self, timeout_s: int = _DEFAULT_TIMEOUT_S) -> None:
        self._timeout_s = timeout_s

    @staticmethod
    def is_available() -> bool:
        """True if the ``claude`` CLI is on PATH."""
        return shutil.which("claude") is not None

    def run(self, prompt_path: Path, context: dict[str, Any]) -> SubagentVerdict:
        if not self.is_available():
            logger.warning("claude CLI not on PATH; subagent unavailable, returning UNCERTAIN")
            return SubagentVerdict.UNCERTAIN

        try:
            prompt_text = Path(prompt_path).read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to read subagent prompt %s: %s", prompt_path, exc)
            return SubagentVerdict.UNCERTAIN

        # Render: prompt text first, then operator context as a fenced JSON block.
        import json as _json

        rendered = (
            f"{prompt_text.rstrip()}\n\n"
            "Operator-supplied context (JSON):\n"
            "```json\n"
            f"{_json.dumps(context, indent=2, sort_keys=True, default=str)}\n"
            "```\n"
        )

        env = {**os.environ, "CLAUDECODE": ""}
        try:
            result = run_utf8(
                ["claude", "--print", rendered],
                env=env,
                timeout=self._timeout_s,
            )
        except subprocess.TimeoutExpired:
            logger.warning("Subagent timed out after %ss on %s", self._timeout_s, prompt_path)
            return SubagentVerdict.UNCERTAIN
        except OSError as exc:
            logger.warning("Subagent invocation failed: %s", exc)
            return SubagentVerdict.UNCERTAIN

        if result.returncode != 0:
            logger.warning(
                "Subagent returned non-zero exit %s; stderr=%s",
                result.returncode,
                (result.stderr or "")[:200],
            )
            return SubagentVerdict.UNCERTAIN

        return _parse_verdict_token(result.stdout)
