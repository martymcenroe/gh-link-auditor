"""Subagent-prompt golden-file regression tests (#312).

Captures the prompt text rendered by each subagent gate / score; compares
to a golden file under ``tests/golden/preflight/``. Catches accidental
prompt drift when refactoring the gate / score callsites.

When prompts intentionally change, regenerate the goldens:

    poetry run pytest -p no:cacheprovider --update-goldens tests/integration/test_preflight_prompts.py

(The --update-goldens flag is wired in conftest.py.)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gh_link_auditor.preflight.subagent import SubagentVerdict
from tests.fakes.subagent import FakeSubagent

_GOLDEN_DIR = Path(__file__).resolve().parent.parent / "golden" / "preflight"


def _read_or_write_golden(name: str, actual: str, update: bool) -> str:
    golden_path = _GOLDEN_DIR / name
    if update:
        _GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        golden_path.write_text(actual, encoding="utf-8")
        return actual
    if not golden_path.exists():
        pytest.skip(f"Golden file {golden_path} missing; run with --update-goldens first")
    return golden_path.read_text(encoding="utf-8")


class TestAntiAiPromptRender:
    def test_prompt_file_exists_and_has_grammar_instructions(self, update_goldens):
        prompt_path = Path("prompts/preflight/ai_scan.txt")
        assert prompt_path.exists()
        content = prompt_path.read_text(encoding="utf-8")
        golden = _read_or_write_golden("ai_scan.txt", content, update_goldens)
        assert content == golden
        # Spot-check the grammar requirement
        assert "single token" in content.lower() or "exactly one" in content.lower()


class TestContentEquivPromptRender:
    def test_prompt_file_exists_and_has_grammar_instructions(self, update_goldens):
        prompt_path = Path("prompts/preflight/content_equiv.txt")
        assert prompt_path.exists()
        content = prompt_path.read_text(encoding="utf-8")
        golden = _read_or_write_golden("content_equiv.txt", content, update_goldens)
        assert content == golden
        assert "single token" in content.lower() or "exactly one" in content.lower()

    def test_prompt_has_url_normalization_step(self):
        """#349: subagent must be told to normalize before judging.

        Pinning the normalization-step header + two of its load-bearing
        dimensions (trailing-slash, query-parameter ordering) catches a
        future "simplify the prompt" PR that drops the section entirely.
        """
        content = Path("prompts/preflight/content_equiv.txt").read_text(encoding="utf-8")
        assert "Normalize before judging" in content
        assert "trailing slash" in content.lower()
        assert "query-parameter" in content.lower() or "query parameter" in content.lower()

    def test_prompt_has_github_org_rename_example(self):
        """#349: explicit GitHub-org-rename example anchors the C5 verdict.

        The 2026-05-26 act-now-coalition/covid-data-model preflight was
        rejected because the subagent classified an org-rename redirect
        as `unrelated`. The example is the regression test against that.
        """
        content = Path("prompts/preflight/content_equiv.txt").read_text(encoding="utf-8")
        assert "GitHub repo rename" in content
        assert "old-org" in content and "new-org" in content


class TestRedirectTargetPromptRender:
    def test_prompt_file_exists_and_has_grammar_instructions(self, update_goldens):
        prompt_path = Path("prompts/preflight/redirect_target.txt")
        assert prompt_path.exists()
        content = prompt_path.read_text(encoding="utf-8")
        golden = _read_or_write_golden("redirect_target.txt", content, update_goldens)
        assert content == golden
        assert "single token" in content.lower() or "exactly one" in content.lower()


class TestFakeSubagentRecordsPrompt:
    def test_fake_records_prompt_path_and_context(self, tmp_path):
        fake = FakeSubagent.configure(default=SubagentVerdict.CLEAN)
        prompt = tmp_path / "p.txt"
        prompt.write_text("scan body", encoding="utf-8")
        fake.run(prompt, {"repo": "owner/r", "texts": {"README.md": "content"}})
        assert len(fake.calls) == 1
        assert fake.calls[0].prompt_path == prompt
        assert fake.calls[0].context == {"repo": "owner/r", "texts": {"README.md": "content"}}
