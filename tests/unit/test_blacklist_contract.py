"""Pin the H5 contract: is_blacklisted must be called with both repo_url and
maintainer at every call site in src/ and tools/.

Rule H5 (see data/regression-audit-2026-05-26.md): blacklisting only at repo
level lets the same maintainer's OTHER repos get targeted. PR #325 wired the
maintainer column and the first two callers (PR-epsilon #290, PR-zeta #208).
This test ensures every subsequent caller also passes both axes -- continuous
enforcement instead of manual audit per Closes #370.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = REPO_ROOT / "src" / "gh_link_auditor"
TOOLS_DIR = REPO_ROOT / "tools"

_KW_NAMES = {"repo_url", "maintainer"}


def _collect_violations(directory: Path) -> list[str]:
    """Return a list of "path:line" for every is_blacklisted(...) call with
    fewer than 2 effective arguments (positional + relevant kwargs)."""
    violations: list[str] = []
    for py_file in sorted(directory.rglob("*.py")):
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            is_match = (isinstance(func, ast.Attribute) and func.attr == "is_blacklisted") or (
                isinstance(func, ast.Name) and func.id == "is_blacklisted"
            )
            if not is_match:
                continue
            n_positional = len(node.args)
            n_kwargs = sum(1 for kw in node.keywords if kw.arg in _KW_NAMES)
            if n_positional + n_kwargs < 2:
                rel = py_file.relative_to(REPO_ROOT).as_posix()
                violations.append(f"{rel}:{node.lineno}")
    return violations


def test_is_blacklisted_callers_in_src_pass_both_args() -> None:
    """Every is_blacklisted(...) call in src/gh_link_auditor/ must pass both
    repo_url and maintainer. Repo-only checks let the same maintainer's other
    repos get targeted. See rule H5 in data/regression-audit-2026-05-26.md."""
    violations = _collect_violations(SRC_DIR)
    assert not violations, (
        "is_blacklisted callers in src/ must pass both repo_url and maintainer "
        "(rule H5). Either supply maintainer explicitly or pass `maintainer=None` "
        "if the call site genuinely cannot resolve one. Violations: "
        f"{violations}"
    )


def test_is_blacklisted_callers_in_tools_pass_both_args() -> None:
    """Same rule applied to tools/, which contains the campaign-driving
    scripts. Skipping these would let the rule degrade asymmetrically."""
    violations = _collect_violations(TOOLS_DIR)
    assert not violations, (
        f"is_blacklisted callers in tools/ must pass both repo_url and maintainer (rule H5). Violations: {violations}"
    )


def test_definition_signature_accepts_maintainer() -> None:
    """The function being checked is real: UnifiedDatabase.is_blacklisted
    accepts an optional maintainer kwarg. If the signature ever changes,
    this test surfaces it before the call-site test does, with a clearer
    failure message."""
    from gh_link_auditor.unified_db import UnifiedDatabase

    sig = UnifiedDatabase.is_blacklisted.__doc__ or ""  # docstring may be empty
    # Use inspect for the real check; docstring is only a tiebreaker.
    import inspect

    params = inspect.signature(UnifiedDatabase.is_blacklisted).parameters
    assert "repo_url" in params, "UnifiedDatabase.is_blacklisted must accept repo_url"
    assert "maintainer" in params, (
        "UnifiedDatabase.is_blacklisted must accept maintainer (rule H5 -- see data/regression-audit-2026-05-26.md)"
    )
    # Suppress unused-variable lint -- sig may be referenced in future asserts.
    del sig
