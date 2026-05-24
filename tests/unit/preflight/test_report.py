"""Tests for src/gh_link_auditor/preflight/report.py (#286)."""

from __future__ import annotations

import json

from gh_link_auditor.preflight.report import (
    GateResult,
    PreflightReport,
    PreflightVerdict,
    ScoreComponent,
    render_json,
    render_markdown,
    save_report,
)


def _make_report(**overrides) -> PreflightReport:
    defaults: dict = {
        "repo_full_name": "owner/repo",
        "candidate": {
            "dead_url": "https://dead.example/x",
            "candidate_url": "https://alive.example/x",
            "source_file": "README.md",
            "line_number": 47,
            "method": "github_api_redirect",
        },
        "verdict": PreflightVerdict.PASS,
        "score": 95,
        "threshold": 90,
        "gate_results": [],
        "score_breakdown": [],
        "gate_failure_name": None,
        "run_id": "preflight-test",
        "skip_preflight_banner": False,
    }
    defaults.update(overrides)
    return PreflightReport(**defaults)


class TestPreflightVerdict:
    def test_enum_values(self):
        assert PreflightVerdict.PASS.value == "pass"
        assert PreflightVerdict.HARD_GATE_FAILED.value == "hard_gate_failed"
        assert PreflightVerdict.NEEDS_OPERATOR_REVIEW.value == "needs_operator_review"
        assert PreflightVerdict.SCORE_TOO_LOW.value == "score_too_low"


class TestPreflightReportDataclass:
    def test_post_init_populates_timestamps(self):
        report = _make_report()
        assert report.started_at  # non-empty
        assert report.completed_at == report.started_at  # defaults match

    def test_explicit_timestamps_preserved(self):
        report = _make_report(started_at="2026-05-24T10:00:00+00:00", completed_at="2026-05-24T10:00:01+00:00")
        assert report.started_at == "2026-05-24T10:00:00+00:00"
        assert report.completed_at == "2026-05-24T10:00:01+00:00"


class TestRenderMarkdown:
    def test_pass_verdict_minimal(self):
        report = _make_report()
        md = render_markdown(report)
        assert "Preflight Report — owner/repo" in md
        assert "Verdict:** `pass`" in md
        assert "Score:** 95 / 100 (threshold: 90)" in md
        assert "OPERATOR REVIEW NEEDED" not in md  # no banner on PASS

    def test_operator_review_banner_present_when_needed(self):
        report = _make_report(verdict=PreflightVerdict.NEEDS_OPERATOR_REVIEW, score=0)
        md = render_markdown(report)
        assert "OPERATOR REVIEW NEEDED" in md
        assert "ghla blacklist add" in md
        assert "--skip-preflight" in md

    def test_skip_preflight_banner_present_when_set(self):
        report = _make_report(skip_preflight_banner=True)
        md = render_markdown(report)
        assert "SKIP-PREFLIGHT BANNER" in md
        assert "advisory only" in md

    def test_gate_rows_rendered(self):
        report = _make_report(
            gate_results=[
                GateResult(name="anti_ai", passed=True, reason="clean", evidence={"files": 7}),
                GateResult(name="archived", passed=False, reason="repo is archived", evidence={"archived": True}),
            ],
            verdict=PreflightVerdict.HARD_GATE_FAILED,
            gate_failure_name="archived",
        )
        md = render_markdown(report)
        assert "`anti_ai`" in md
        assert "`archived`" in md
        assert "Failed gate:** `archived`" in md
        assert "files=7" in md

    def test_score_rows_rendered_with_total(self):
        report = _make_report(
            score=18,
            score_breakdown=[
                ScoreComponent(name="C1", points_awarded=10, max_points=10, evidence={"match": "exact"}),
                ScoreComponent(name="C2", points_awarded=8, max_points=10, evidence={"hits": 2}),
            ],
        )
        md = render_markdown(report)
        assert "C1" in md
        assert "C2" in md
        assert "**Total**" in md
        assert "**18**" in md

    def test_operator_links_present(self):
        report = _make_report()
        md = render_markdown(report)
        assert "https://github.com/owner" in md
        assert "https://github.com/owner/repo/pulls" in md
        assert "<https://dead.example/x>" in md


class TestRenderJson:
    def test_returns_valid_json(self):
        report = _make_report()
        s = render_json(report)
        data = json.loads(s)
        assert data["repo_full_name"] == "owner/repo"
        assert data["verdict"] == "pass"
        assert data["score"] == 95
        assert data["threshold"] == 90
        assert data["gate_results"] == []
        assert data["score_breakdown"] == []

    def test_includes_gates_and_scores(self):
        report = _make_report(
            gate_results=[GateResult(name="anti_ai", passed=True, reason="ok")],
            score_breakdown=[ScoreComponent(name="C1", points_awarded=10, max_points=10)],
        )
        data = json.loads(render_json(report))
        assert len(data["gate_results"]) == 1
        assert data["gate_results"][0]["name"] == "anti_ai"
        assert data["gate_results"][0]["passed"] is True
        assert len(data["score_breakdown"]) == 1
        assert data["score_breakdown"][0]["points_awarded"] == 10


class TestSaveReport:
    def test_writes_both_files(self, tmp_path):
        report = _make_report()
        md_path, json_path = save_report(report, tmp_path)
        assert md_path.exists()
        assert json_path.exists()
        # File names use the run_id + safe repo name
        assert md_path.name == "preflight-test-owner_repo.md"
        assert json_path.name == "preflight-test-owner_repo.json"

    def test_creates_log_dir_if_missing(self, tmp_path):
        target = tmp_path / "nested" / "preflight-reports"
        report = _make_report()
        md_path, _ = save_report(report, target)
        assert target.exists()
        assert md_path.exists()

    def test_contents_match_renderers(self, tmp_path):
        report = _make_report()
        md_path, json_path = save_report(report, tmp_path)
        assert md_path.read_text(encoding="utf-8") == render_markdown(report)
        assert json_path.read_text(encoding="utf-8") == render_json(report)
