"""Shared test fixtures for gh-link-auditor."""

import pytest

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
