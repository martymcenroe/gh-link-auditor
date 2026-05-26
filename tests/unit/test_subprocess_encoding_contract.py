"""Project-wide lint: subprocess.run(..., text=True, ...) must pass encoding=.

PR #338 fixed four sites in the preflight package where ``text=True`` alone
gave Windows cp1252 stdout, which can't represent UTF-8 GitHub API output
(emoji, accents, non-Latin chars). PR #367 lifted the preflight fix into
``preflight/_subproc.py``. This test enforces the same rule project-wide --
every ``subprocess.run(..., text=True, ...)`` call in ``src/`` and
``tools/`` must also pass an explicit ``encoding=`` kwarg.

The rule is a pre-commit-style lint check via AST walk. Adding a new
violating call to any tracked .py file in ``src/`` or ``tools/`` breaks
this test.

See data/regression-audit-2026-05-26.md section R5 (helper) and R15
(this rule). #371.
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = REPO_ROOT / "src"
TOOLS_DIR = REPO_ROOT / "tools"


def _has_kwarg(node: ast.Call, name: str) -> bool:
    return any(kw.arg == name for kw in node.keywords)


def _kwarg_is_true(node: ast.Call, name: str) -> bool:
    for kw in node.keywords:
        if kw.arg == name and isinstance(kw.value, ast.Constant) and kw.value.value is True:
            return True
    return False


def _find_violations(directory: Path) -> list[str]:
    """Return "path:line" for every subprocess.run(... text=True ...) call
    in `directory` that does not also pass `encoding=`. Returns empty if
    the directory does not exist (e.g. fresh checkout with no tools/)."""
    violations: list[str] = []
    if not directory.exists():
        return violations
    for py_file in sorted(directory.rglob("*.py")):
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            # Match subprocess.run(...)
            if not (
                isinstance(func, ast.Attribute)
                and func.attr == "run"
                and isinstance(func.value, ast.Name)
                and func.value.id == "subprocess"
            ):
                continue
            if not _kwarg_is_true(node, "text"):
                # text=False (default) -> bytes -> encoding kwarg is irrelevant
                continue
            if _has_kwarg(node, "encoding"):
                continue
            try:
                rel = py_file.relative_to(REPO_ROOT).as_posix()
            except ValueError:
                # Synthetic tmp_path file in the detector's own tests
                rel = py_file.as_posix()
            violations.append(f"{rel}:{node.lineno}")
    return violations


def test_src_subprocess_run_calls_pass_encoding() -> None:
    """Every subprocess.run(text=True) in src/ must also pass encoding=.

    The encoding default on Windows is cp1252; UTF-8 from the GitHub
    API breaks decoding on the first non-ASCII byte. Pass
    encoding="utf-8", errors="replace" to make it cp1252-safe.
    """
    violations = _find_violations(SRC_DIR)
    assert not violations, (
        "subprocess.run(..., text=True, ...) calls in src/ must also pass "
        'encoding="utf-8", errors="replace". Without it, Windows cp1252 '
        "breaks decoding GitHub API responses with non-ASCII bytes. "
        "See data/regression-audit-2026-05-26.md sections R5/R15. "
        "Or route through src/gh_link_auditor/preflight/_subproc.py "
        f"(run_utf8 / gh_api_json). Violations: {violations}"
    )


def test_tools_subprocess_run_calls_pass_encoding() -> None:
    """Same rule, tools/ scope. tools/ contains campaign-driving scripts
    that hit the GitHub API; they need the same cp1252 protection."""
    violations = _find_violations(TOOLS_DIR)
    assert not violations, (
        "subprocess.run(..., text=True, ...) calls in tools/ must also pass "
        'encoding="utf-8", errors="replace". '
        f"Violations: {violations}"
    )


def test_detector_catches_synthetic_violation(tmp_path: Path) -> None:
    """Pin the detector itself: a deliberate violation file MUST be
    flagged. If a future refactor breaks the AST walker, this test fails
    before the production-code tests do, with a cleaner failure message."""
    bad = tmp_path / "bad.py"
    bad.write_text(
        textwrap.dedent(
            """
            import subprocess

            def go() -> None:
                subprocess.run(["echo", "hi"], capture_output=True, text=True)
            """
        ).strip(),
        encoding="utf-8",
    )
    violations = _find_violations(tmp_path)
    assert any("bad.py" in v for v in violations), (
        f"detector failed to flag the synthetic text=True/no-encoding call. violations: {violations}"
    )


def test_detector_accepts_text_with_encoding(tmp_path: Path) -> None:
    """Pin the detector positively: a compliant call MUST NOT be flagged."""
    good = tmp_path / "good.py"
    good.write_text(
        textwrap.dedent(
            """
            import subprocess

            def go() -> None:
                subprocess.run(
                    ["echo", "hi"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
            """
        ).strip(),
        encoding="utf-8",
    )
    violations = _find_violations(tmp_path)
    assert not violations, f"detector wrongly flagged a compliant call: {violations}"


def test_detector_ignores_text_false(tmp_path: Path) -> None:
    """text=False (or default) returns bytes; encoding= is irrelevant
    there. Detector must not flag that case."""
    fine = tmp_path / "fine.py"
    fine.write_text(
        textwrap.dedent(
            """
            import subprocess

            def go() -> None:
                subprocess.run(["echo", "hi"], capture_output=True)
            """
        ).strip(),
        encoding="utf-8",
    )
    violations = _find_violations(tmp_path)
    assert not violations, f"detector wrongly flagged a text=False call: {violations}"
