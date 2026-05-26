"""Pin the "only one place" rule for subprocess.run inside preflight.

Per audit section R5 and PR #338: every ``subprocess.run(... text=True ...)``
call inside ``src/gh_link_auditor/preflight/`` must live in ``_subproc.py``.
Any new subprocess call elsewhere in the package breaks this test --
forcing the author to route through ``run_utf8`` / ``gh_api_json`` and
inherit the cp1252-safe defaults.

See #367.
"""

from __future__ import annotations

import ast
from pathlib import Path

PREFLIGHT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "src" / "gh_link_auditor" / "preflight"
ALLOWED_FILE = PREFLIGHT_DIR / "_subproc.py"


def _file_has_subprocess_run(py_file: Path) -> bool:
    """Return True if the file's AST contains any subprocess.run(...) call."""
    try:
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # Match subprocess.run(...)
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "run"
            and isinstance(func.value, ast.Name)
            and func.value.id == "subprocess"
        ):
            return True
    return False


def test_subprocess_run_only_in_subproc_module() -> None:
    """Walk src/gh_link_auditor/preflight/*.py; assert subprocess.run only
    appears inside _subproc.py. Future additions must route through the
    helper instead."""
    offenders: list[str] = []
    for py_file in sorted(PREFLIGHT_DIR.rglob("*.py")):
        if py_file == ALLOWED_FILE:
            continue
        if _file_has_subprocess_run(py_file):
            offenders.append(py_file.relative_to(PREFLIGHT_DIR).as_posix())
    assert not offenders, (
        "subprocess.run must only appear in _subproc.py inside the "
        "preflight package. Route any other invocation through "
        "_subproc.run_utf8 or _subproc.gh_api_json so the UTF-8 encoding "
        "contract is inherited automatically. See data/regression-audit-"
        f"2026-05-26.md section R5. Offending files: {offenders}"
    )


def test_subproc_module_is_the_only_one_calling_subprocess_run() -> None:
    """Positive case: _subproc.py itself does call subprocess.run.
    Surfaces a clearer failure than the previous test if someone
    accidentally deletes the helper or replaces it with something else."""
    assert _file_has_subprocess_run(ALLOWED_FILE), (
        f"{ALLOWED_FILE.relative_to(PREFLIGHT_DIR)} must wrap subprocess.run -- "
        "if you renamed the helper or removed it, update the AST scan and "
        "the call-site imports accordingly."
    )
