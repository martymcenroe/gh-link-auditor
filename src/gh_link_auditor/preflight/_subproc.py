"""Shared subprocess wrapper for the preflight package.

Every `subprocess.run(... text=True ...)` call inside
``src/gh_link_auditor/preflight/`` MUST come through this module. This
is the only place that combines ``text=True`` with
``encoding="utf-8"`` and ``errors="replace"``. Without that pairing,
Windows cp1252 stdout breaks on the first emoji or accented character
in GitHub API output -- the bug fixed by PR #338 in four call sites.

The "only one place" rule is pinned by
``tests/unit/preflight/test_subproc_pin.py``.

See ``data/regression-audit-2026-05-26.md`` section R5.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping, Sequence
from typing import Any


def run_utf8(
    args: Sequence[str],
    *,
    timeout: float | None = 30,
    env: Mapping[str, str] | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess with UTF-8 text-mode capture and a consistent policy.

    Wraps ``subprocess.run`` with ``capture_output=True``, ``text=True``,
    ``encoding="utf-8"`` and ``errors="replace"``. Returns the
    ``CompletedProcess`` unchanged so callers can read returncode,
    stdout, stderr directly.

    Raises ``subprocess.TimeoutExpired``, ``FileNotFoundError`` (binary
    missing) and other ``OSError`` subclasses; the caller decides how to
    handle them.
    """
    return subprocess.run(
        list(args),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=dict(env) if env is not None else None,
        check=check,
    )


def gh_api_json(path: str, *, timeout: float = 30) -> Any:
    """Call ``gh api {path}`` and return parsed JSON, or None on any failure.

    All four failure modes coerce to None so callers don't need to
    repeat the try/except gauntlet:

    - ``gh`` binary missing on PATH (FileNotFoundError)
    - subprocess timeout (TimeoutExpired)
    - non-zero exit (gh writes the error to stderr)
    - empty stdout
    - malformed JSON
    """
    try:
        result = run_utf8(["gh", "api", path], timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
