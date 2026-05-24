"""Tests for src/gh_link_auditor/preflight/subagent.py (#287)."""

from __future__ import annotations

import subprocess
from unittest import mock

from gh_link_auditor.preflight.subagent import (
    RealSubagent,
    SubagentVerdict,
    _parse_verdict_token,
    anti_ai_keyword_fallback,
)
from tests.fakes.subagent import FakeSubagent


class TestParseVerdictToken:
    def test_clean(self):
        assert _parse_verdict_token("clean") == SubagentVerdict.CLEAN

    def test_uncertain(self):
        assert _parse_verdict_token("uncertain") == SubagentVerdict.UNCERTAIN

    def test_hostile(self):
        assert _parse_verdict_token("hostile") == SubagentVerdict.HOSTILE

    def test_partial(self):
        assert _parse_verdict_token("partial") == SubagentVerdict.PARTIAL

    def test_unrelated(self):
        assert _parse_verdict_token("unrelated") == SubagentVerdict.UNRELATED

    def test_uppercase_input(self):
        assert _parse_verdict_token("CLEAN") == SubagentVerdict.CLEAN

    def test_with_extra_whitespace(self):
        assert _parse_verdict_token("  hostile  \n") == SubagentVerdict.HOSTILE

    def test_unknown_token_returns_uncertain(self):
        assert _parse_verdict_token("maybe") == SubagentVerdict.UNCERTAIN

    def test_empty_returns_uncertain(self):
        assert _parse_verdict_token("") == SubagentVerdict.UNCERTAIN

    def test_uses_first_line_only(self):
        assert _parse_verdict_token("clean\nextra noise") == SubagentVerdict.CLEAN


class TestAntiAiKeywordFallback:
    def test_clean_when_no_hits(self):
        assert anti_ai_keyword_fallback("Welcome to our project") == SubagentVerdict.CLEAN

    def test_uncertain_on_hit(self):
        assert anti_ai_keyword_fallback("Please do not use AI to generate this") == SubagentVerdict.UNCERTAIN

    def test_clean_on_empty(self):
        assert anti_ai_keyword_fallback("") == SubagentVerdict.CLEAN

    def test_clean_on_none(self):
        assert anti_ai_keyword_fallback(None) == SubagentVerdict.CLEAN

    def test_case_insensitive(self):
        assert anti_ai_keyword_fallback("NO LLM CONTRIBUTIONS") == SubagentVerdict.UNCERTAIN


class TestRealSubagent:
    def test_returns_uncertain_when_claude_missing(self, tmp_path):
        prompt = tmp_path / "p.txt"
        prompt.write_text("scan", encoding="utf-8")
        subagent = RealSubagent()
        with mock.patch("gh_link_auditor.preflight.subagent.shutil.which", return_value=None):
            verdict = subagent.run(prompt, {"x": 1})
        assert verdict == SubagentVerdict.UNCERTAIN

    def test_returns_uncertain_on_timeout(self, tmp_path):
        prompt = tmp_path / "p.txt"
        prompt.write_text("scan", encoding="utf-8")
        subagent = RealSubagent(timeout_s=1)
        with (
            mock.patch("gh_link_auditor.preflight.subagent.shutil.which", return_value="/usr/bin/claude"),
            mock.patch(
                "gh_link_auditor.preflight.subagent.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=1),
            ),
        ):
            verdict = subagent.run(prompt, {"x": 1})
        assert verdict == SubagentVerdict.UNCERTAIN

    def test_returns_uncertain_on_nonzero_exit(self, tmp_path):
        prompt = tmp_path / "p.txt"
        prompt.write_text("scan", encoding="utf-8")
        subagent = RealSubagent()
        completed = subprocess.CompletedProcess(args=["claude"], returncode=1, stdout="", stderr="boom")
        with (
            mock.patch("gh_link_auditor.preflight.subagent.shutil.which", return_value="/usr/bin/claude"),
            mock.patch("gh_link_auditor.preflight.subagent.subprocess.run", return_value=completed),
        ):
            verdict = subagent.run(prompt, {"x": 1})
        assert verdict == SubagentVerdict.UNCERTAIN

    def test_returns_parsed_verdict_on_success(self, tmp_path):
        prompt = tmp_path / "p.txt"
        prompt.write_text("ai_scan", encoding="utf-8")
        subagent = RealSubagent()
        completed = subprocess.CompletedProcess(args=["claude"], returncode=0, stdout="hostile\n", stderr="")
        with (
            mock.patch("gh_link_auditor.preflight.subagent.shutil.which", return_value="/usr/bin/claude"),
            mock.patch("gh_link_auditor.preflight.subagent.subprocess.run", return_value=completed) as run_mock,
        ):
            verdict = subagent.run(prompt, {"repo": "owner/r"})
        assert verdict == SubagentVerdict.HOSTILE
        # Confirms the env carried CLAUDECODE=""
        env = run_mock.call_args.kwargs["env"]
        assert env["CLAUDECODE"] == ""

    def test_returns_uncertain_when_prompt_unreadable(self, tmp_path):
        missing = tmp_path / "missing.txt"  # not created
        subagent = RealSubagent()
        with mock.patch("gh_link_auditor.preflight.subagent.shutil.which", return_value="/usr/bin/claude"):
            verdict = subagent.run(missing, {"x": 1})
        assert verdict == SubagentVerdict.UNCERTAIN

    def test_is_available_reflects_shutil_which(self):
        with mock.patch("gh_link_auditor.preflight.subagent.shutil.which", return_value="/usr/bin/claude"):
            assert RealSubagent.is_available() is True
        with mock.patch("gh_link_auditor.preflight.subagent.shutil.which", return_value=None):
            assert RealSubagent.is_available() is False


class TestFakeSubagent:
    def test_default_verdict_returned(self, tmp_path):
        fake = FakeSubagent.configure(default=SubagentVerdict.CLEAN)
        verdict = fake.run(tmp_path / "p.txt", {"x": 1})
        assert verdict == SubagentVerdict.CLEAN
        assert len(fake.calls) == 1
        assert fake.calls[0].context == {"x": 1}

    def test_per_prompt_override(self, tmp_path):
        p1 = tmp_path / "a.txt"
        p2 = tmp_path / "b.txt"
        fake = FakeSubagent.configure(
            default=SubagentVerdict.CLEAN,
            overrides={str(p1): SubagentVerdict.HOSTILE},
        )
        assert fake.run(p1, {}) == SubagentVerdict.HOSTILE
        assert fake.run(p2, {}) == SubagentVerdict.CLEAN

    def test_records_every_call(self, tmp_path):
        fake = FakeSubagent.configure()
        for i in range(3):
            fake.run(tmp_path / f"{i}.txt", {"i": i})
        assert len(fake.calls) == 3
        assert [c.context["i"] for c in fake.calls] == [0, 1, 2]

    def test_copies_context_dict(self, tmp_path):
        fake = FakeSubagent.configure()
        ctx = {"x": 1}
        fake.run(tmp_path / "p.txt", ctx)
        ctx["x"] = 999  # mutating after should not affect the recording
        assert fake.calls[0].context == {"x": 1}
