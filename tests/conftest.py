"""Shared test fixtures for gh-link-auditor."""

import os
import sys
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# #421: production-data isolation.
#
# The suite must NEVER touch the real ~/.ghla (unified DB) or the real
# data/preflight-reports/. DEFAULT_DB_PATH is Path.home()/".ghla"/"ghla.db",
# evaluated at gh_link_auditor.unified_db IMPORT time and re-exported by
# import into other modules — monkeypatching the name later cannot reach
# already-bound references. This conftest imports before any test module,
# so redirecting the home env vars HERE isolates every default-path resolver
# in one move. (Documented incident: 124 phantom PR increments accumulated on
# a literal "org/repo" row in the production DB over 2.5 months of local runs.)
#
# Live runs (--live) keep the real home: RealSubagent shells out to the
# claude CLI, which needs real ~/.claude credentials. Live is deliberate,
# operator-attended context.
# ---------------------------------------------------------------------------

_REAL_HOME = Path.home()

if "--live" not in sys.argv:
    _TEST_HOME = Path(tempfile.mkdtemp(prefix="ghla-test-home-"))
    os.environ["USERPROFILE"] = str(_TEST_HOME)  # Windows Path.home()
    os.environ["HOME"] = str(_TEST_HOME)  # POSIX Path.home()


@pytest.fixture(scope="session", autouse=True)
def _no_production_leaks():
    """#421 regression guard: fail the run if production surfaces changed.

    Catches what the home redirect cannot (e.g. __file__-relative report
    writers) and fails fast if a future change re-introduces a leak path.
    """
    real_db = _REAL_HOME / ".ghla" / "ghla.db"
    db_before = (real_db.stat().st_mtime_ns, real_db.stat().st_size) if real_db.exists() else None
    reports_dir = Path(__file__).resolve().parent.parent / "data" / "preflight-reports"
    reports_before = {p.name for p in reports_dir.iterdir()} if reports_dir.exists() else set()

    yield

    db_after = (real_db.stat().st_mtime_ns, real_db.stat().st_size) if real_db.exists() else None
    assert db_after == db_before, "TEST LEAK (#421): the suite modified the real ~/.ghla/ghla.db"
    reports_after = {p.name for p in reports_dir.iterdir()} if reports_dir.exists() else set()
    leaked = reports_after - reports_before
    assert not leaked, f"TEST LEAK (#421): real data/preflight-reports gained files: {sorted(leaked)[:5]}"


# ---------------------------------------------------------------------------
# Phase B preflight test infrastructure (#311 live; #312 goldens)
# ---------------------------------------------------------------------------


def pytest_addoption(parser):
    """Wire ``--live`` and ``--update-goldens`` CLI flags."""
    parser.addoption(
        "--live",
        action="store_true",
        default=False,
        help="run @pytest.mark.live tests (real network + real subagent; opt-in)",
    )
    parser.addoption(
        "--update-goldens",
        action="store_true",
        default=False,
        help="regenerate golden files instead of comparing (tests/integration/test_preflight_prompts.py)",
    )


def pytest_collection_modifyitems(config, items):
    """Skip live-marked tests unless --live is passed."""
    if config.getoption("--live"):
        return
    skip_live = pytest.mark.skip(reason="live tests are opt-in; pass --live to run")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)


@pytest.fixture
def update_goldens(request) -> bool:
    """True when --update-goldens was passed; consumed by golden-file tests."""
    return bool(request.config.getoption("--update-goldens"))


@pytest.fixture
def sample_markdown(tmp_path):
    """Create a temporary markdown file with sample URLs."""
    content = """# Test Document

Check out [Example](https://example.com) and [Python](https://www.python.org).

Broken link: [Missing](https://httpbin.org/status/404)
"""
    md_file = tmp_path / "test.md"
    md_file.write_text(content)
    return str(md_file)


@pytest.fixture
def empty_markdown(tmp_path):
    """Create a temporary markdown file with no URLs."""
    md_file = tmp_path / "empty.md"
    md_file.write_text("# No links here\n\nJust plain text.\n")
    return str(md_file)
