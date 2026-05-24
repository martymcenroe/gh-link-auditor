"""Recordable fake subagent for preflight tests (#287).

Replaces what would otherwise be a ``unittest.mock.patch("subprocess.run")``
with a typed, predictable fake. Project rule: NO MagicMock — use
``tests/fakes/`` patterns. See ``tests/fakes/http.py:FakeURLResponse`` for
the same pattern.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gh_link_auditor.preflight.subagent import SubagentVerdict


@dataclass
class _Call:
    prompt_path: Path
    context: dict[str, Any]


@dataclass
class FakeSubagent:
    """Fake Subagent that returns canned verdicts and records every call."""

    # Default verdict returned when no per-prompt override is configured.
    default_verdict: SubagentVerdict = SubagentVerdict.CLEAN

    # Optional per-prompt-path overrides. Lookup key is the absolute or
    # relative path string (whichever the caller passes — both forms match
    # via Path resolution in ``run``).
    overrides: dict[str, SubagentVerdict] = field(default_factory=dict)

    # Recording of every call made to ``run``.
    calls: list[_Call] = field(default_factory=list)

    @classmethod
    def configure(
        cls,
        default: SubagentVerdict = SubagentVerdict.CLEAN,
        overrides: dict[str, SubagentVerdict] | None = None,
    ) -> FakeSubagent:
        """Create a FakeSubagent with the given defaults / overrides."""
        return cls(default_verdict=default, overrides=overrides or {})

    def run(self, prompt_path: Path, context: dict[str, Any]) -> SubagentVerdict:
        self.calls.append(_Call(prompt_path=Path(prompt_path), context=dict(context)))
        key = str(prompt_path)
        if key in self.overrides:
            return self.overrides[key]
        return self.default_verdict
