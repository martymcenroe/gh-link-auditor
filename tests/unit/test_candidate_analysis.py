"""Tests for the candidate-analysis tool (#403). See LLD-403."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pytest

from gh_link_auditor.candidate_analysis import (
    SECTION_KEYS,
    CandidateNotFound,
    PreflightReportNotFound,
    build_analysis,
    find_candidate_row,
    render_json,
    render_markdown,
    row_to_fix,
    row_to_verdict,
)
from gh_link_auditor.cli.candidate_analysis_cmd import (
    build_candidate_analysis_parser,
    cmd_candidate_analysis,
)
from gh_link_auditor.pipeline.pr_message import (
    generate_pr_body_from_fixes,
    generate_pr_title_from_fixes,
)
from gh_link_auditor.unified_db import UnifiedDatabase
from tests.fakes.github_facade import FakeGitHubFacade

REPO = "acme/widgets"
DEAD = "https://old.example.com/docs/install"
CAND = "https://new.example.com/docs/install"


def _insert_candidate(db: UnifiedDatabase, **overrides: Any) -> None:
    row = {
        "run_id": "bulk-test",
        "repo_full_name": REPO,
        "source_file": "README.md",
        "line_number": 12,
        "dead_url": DEAD,
        "candidate_url": CAND,
        "method": "github_api_redirect",
        "tier": 1,
        "similarity_score": 1.0,
        "verified_live": 1,
        "confidence": 0.95,
        "surfaced": 0,
        "created_at": "2026-07-28T00:00:00+00:00",
        "investigation_state": "derived_candidate",
    }
    row.update(overrides)
    db._conn.execute(
        """INSERT INTO bulk_scan_findings
           (run_id, repo_full_name, source_file, line_number, dead_url, candidate_url,
            method, tier, similarity_score, verified_live, confidence, surfaced,
            created_at, investigation_state)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        tuple(row.values()),
    )
    db._conn.commit()


def _all_pass_gates() -> list[dict[str, Any]]:
    names = [
        "anti_ai",
        "repo_active",
        "blacklist",
        "dead_url_still_present",
        "dead_url_still_dead",
        "candidate_url_alive",
        "redirect_target_related",
        "no_duplicate_pr",
        "no_markdown_corruption",
        "stars_floor",
    ]
    return [{"name": n, "passed": True, "reason": "ok", "evidence": {"k": "v"}} for n in names]


def _full_scores() -> list[dict[str, Any]]:
    maxes = {
        "C1": 10,
        "C2": 10,
        "C3": 10,
        "C4": 10,
        "C5": 15,
        "C6": 10,
        "C7": 10,
        "R1": 5,
        "R2": 5,
        "R3": 5,
        "R4": 5,
        "R5": 5,
    }
    return [{"name": k, "points_awarded": v, "max_points": v, "evidence": {"e": 1}} for k, v in maxes.items()]


def _write_report(
    reports_dir: Path,
    gates: list[dict[str, Any]] | None = None,
    scores: list[dict[str, Any]] | None = None,
    verdict: str = "pass",
    score: int = 100,
) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "repo_full_name": REPO,
        "verdict": verdict,
        "score": score,
        "threshold": 90,
        "gate_results": gates if gates is not None else _all_pass_gates(),
        "score_breakdown": scores if scores is not None else _full_scores(),
        "run_id": "preflight-20260728T120000Z-abc123",
        "candidate": {"dead_url": DEAD, "candidate_url": CAND},
    }
    safe = REPO.replace("/", "_")
    path = reports_dir / f"preflight-20260728T120000Z-abc123-{safe}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    (reports_dir / f"preflight-20260728T120000Z-abc123-{safe}.md").write_text("# stub", encoding="utf-8")
    return path


@pytest.fixture
def db(tmp_path):
    with UnifiedDatabase(str(tmp_path / "t.db")) as udb:
        _insert_candidate(udb)
        yield udb


@pytest.fixture
def reports_dir(tmp_path):
    d = tmp_path / "reports"
    _write_report(d)
    return d


@pytest.fixture
def facade():
    return FakeGitHubFacade(
        metadata={
            "full_name": REPO,
            "description": "widget tools",
            "language": "Python",
            "license": {"spdx_id": "MIT"},
            "default_branch": "main",
            "stargazers_count": 400,
            "forks_count": 20,
            "subscribers_count": 9,
            "open_issues_count": 3,
            "owner": {"type": "Organization"},
            "created_at": "2020-01-01T00:00:00Z",
            "pushed_at": "2026-07-27T00:00:00Z",
            "archived": False,
            "disabled": False,
            "fork": False,
        },
        files={"README.md": "\n".join(f"line {i}" for i in range(1, 41))},
        existing_paths={"CONTRIBUTING.md"},
        merged=[
            {
                "number": 10,
                "title": "fix typo in docs",
                "author": {"login": "maria"},
                "mergedAt": "2026-07-20T00:00:00Z",
                "changedFiles": 1,
                "additions": 1,
                "deletions": 1,
            },
            {
                "number": 9,
                "title": "chore(deps): bump x",
                "author": {"login": "dependabot[bot]"},
                "mergedAt": "2026-07-19T00:00:00Z",
                "changedFiles": 1,
                "additions": 2,
                "deletions": 2,
            },
        ],
        open=[{"number": 11, "title": "add feature", "author": {"login": "sam"}, "createdAt": "2026-07-25T00:00:00Z"}],
    )


class TestRowMapping:
    def test_row_to_fix_shape(self):
        fix = row_to_fix({"source_file": "R.md", "dead_url": DEAD, "candidate_url": CAND})
        assert fix == {
            "source_file": "R.md",
            "original_url": DEAD,
            "replacement_url": CAND,
            "unified_diff": "",
        }

    def test_row_to_verdict_defaults(self):
        v = row_to_verdict({"dead_url": DEAD, "candidate_url": CAND})
        assert v["dead_link"]["line_number"] == 0
        assert v["confidence"] == 1.0
        assert v["candidate"]["tier"] == 1
        assert v["approved"] is True


class TestFindCandidateRow:
    def test_raises_when_missing(self, db):
        with pytest.raises(CandidateNotFound):
            find_candidate_row(db, "nobody/here")

    def test_run_id_filter_scopes(self, db):
        with pytest.raises(CandidateNotFound):
            find_candidate_row(db, REPO, run_id="no-such-run")
        assert find_candidate_row(db, REPO, run_id="bulk-test")["repo_full_name"] == REPO


class TestBuildAnalysis:
    def test_all_sections_present_in_json(self, db, reports_dir, facade):
        a = build_analysis(REPO, db, reports_dir=reports_dir, github=facade)
        data = json.loads(render_json(a))
        for key in SECTION_KEYS:
            assert key in data, f"missing section {key}"

    def test_markdown_has_twelve_ordered_headings(self, db, reports_dir, facade):
        md = render_markdown(build_analysis(REPO, db, reports_dir=reports_dir, github=facade))
        positions = [md.index(f"## {i}.") for i in range(1, 13)]
        assert positions == sorted(positions), "sections out of order"

    def test_no_unrendered_placeholders(self, db, reports_dir, facade):
        md = render_markdown(build_analysis(REPO, db, reports_dir=reports_dir, github=facade))
        assert "{" not in md.replace("{}", "")

    def test_urls_section_renders_every_url_as_link(self, db, reports_dir, facade):
        a = build_analysis(REPO, db, reports_dir=reports_dir, github=facade)
        md = render_markdown(a)
        for u in a.urls:
            if u["url"]:
                assert f"<{u['url']}>" in md

    def test_source_context_marks_target_line(self, db, reports_dir, facade):
        a = build_analysis(REPO, db, reports_dir=reports_dir, github=facade)
        assert a.source_context["available"] is True
        assert a.source_context["target"] == 12
        assert any("← THIS LINE (12)" in line for line in a.source_context["lines"])

    def test_source_context_clamps_at_file_start(self, db, reports_dir, facade):
        db._conn.execute("UPDATE bulk_scan_findings SET line_number = 2")
        db._conn.commit()
        a = build_analysis(REPO, db, reports_dir=reports_dir, github=facade)
        assert a.source_context["start"] == 1

    def test_edit_diff_contains_both_urls(self, db, reports_dir, facade):
        a = build_analysis(REPO, db, reports_dir=reports_dir, github=facade)
        assert f"-{DEAD}" in a.edit_diff
        assert f"+{CAND}" in a.edit_diff

    def test_gates_and_scores_lifted_verbatim(self, db, reports_dir, facade):
        a = build_analysis(REPO, db, reports_dir=reports_dir, github=facade)
        assert len(a.hard_gates) == 10
        assert len(a.score_breakdown) == 12

    def test_generated_pr_matches_pr_message_exactly(self, db, reports_dir, facade):
        """Section 9 must call the real generators, not a divergent copy."""
        a = build_analysis(REPO, db, reports_dir=reports_dir, github=facade)
        row = find_candidate_row(db, REPO)
        fixes, verdicts = [row_to_fix(row)], [row_to_verdict(row)]
        assert a.generated_pr["title"] == generate_pr_title_from_fixes(fixes)
        assert a.generated_pr["body"] == generate_pr_body_from_fixes(fixes, verdicts)

    def test_style_notes_count_bots_separately(self, db, reports_dir, facade):
        a = build_analysis(REPO, db, reports_dir=reports_dir, github=facade)
        notes = " ".join(a.maintainer_signals["style_notes"])
        assert "1/2 recent merges are from bots" in notes
        assert "maria" in notes and "dependabot[bot]" not in notes.split("window:")[-1]

    def test_missing_report_raises(self, db, tmp_path, facade):
        with pytest.raises(PreflightReportNotFound):
            build_analysis(REPO, db, reports_dir=tmp_path / "empty", github=facade)


class TestRiskAssessment:
    def test_all_pass_yields_lowest_net_risk(self, db, reports_dir, facade):
        a = build_analysis(REPO, db, reports_dir=reports_dir, github=facade)
        assert a.risk_assessment["net"] == "as low as this campaign produces"
        assert all(r["level"] == "none" for r in a.risk_assessment["rows"])

    def test_failed_gate_forces_hold(self, db, tmp_path, facade):
        gates = _all_pass_gates()
        gates[5] = {"name": "candidate_url_alive", "passed": False, "reason": "404", "evidence": {}}
        d = tmp_path / "r2"
        _write_report(d, gates=gates, verdict="hard_gate_failed", score=0)
        a = build_analysis(REPO, db, reports_dir=d, github=facade)
        assert a.risk_assessment["net"] == "hold"
        assert any(r["level"] == "high" for r in a.risk_assessment["rows"])

    def test_partial_score_yields_moderate(self, db, tmp_path, facade):
        scores = _full_scores()
        for c in scores:
            if c["name"] == "R2":
                c["points_awarded"] = 1
        d = tmp_path / "r3"
        _write_report(d, scores=scores)
        a = build_analysis(REPO, db, reports_dir=d, github=facade)
        assert a.risk_assessment["net"] == "moderate"


class TestNoLive:
    def test_makes_zero_facade_calls(self, db, reports_dir, facade):
        build_analysis(REPO, db, reports_dir=reports_dir, github=facade, live=False)
        assert facade.calls == []

    def test_marks_unknown_fields_and_still_renders(self, db, reports_dir, facade):
        a = build_analysis(REPO, db, reports_dir=reports_dir, github=facade, live=False)
        md = render_markdown(a)
        assert "needs live" in md
        assert a.source_context["available"] is False
        # DB/report-sourced sections still populated
        assert a.edit_diff and a.hard_gates and a.generated_pr["title"]
        assert "ALL live data" in a.unknowns[0]


class TestCli:
    @staticmethod
    def _ns(db, reports_dir, **kw) -> argparse.Namespace:
        base = {
            "repo": REPO,
            "run_id": None,
            "db_path": db,
            "format": "md",
            "out": None,
            "reports_dir": str(reports_dir),
            "no_live": True,
        }
        base.update(kw)
        return argparse.Namespace(**base)

    def test_parser_registration_defaults(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        build_candidate_analysis_parser(sub)
        args = parser.parse_args(["candidate-analysis", REPO])
        assert args.repo == REPO
        assert args.format == "md"
        assert args.no_live is False

    def test_exit_zero_and_prints(self, tmp_path, reports_dir, capsys):
        db_path = str(tmp_path / "c.db")
        with UnifiedDatabase(db_path) as udb:
            _insert_candidate(udb)
        rc = cmd_candidate_analysis(self._ns(db_path, reports_dir))
        assert rc == 0
        assert "# Candidate Analysis" in capsys.readouterr().out

    def test_exit_one_when_no_candidate(self, tmp_path, reports_dir, capsys):
        db_path = str(tmp_path / "empty.db")
        with UnifiedDatabase(db_path):
            pass
        rc = cmd_candidate_analysis(self._ns(db_path, reports_dir))
        assert rc == 1
        assert "no candidate row" in capsys.readouterr().err

    def test_exit_two_when_no_report(self, tmp_path, capsys):
        db_path = str(tmp_path / "c.db")
        with UnifiedDatabase(db_path) as udb:
            _insert_candidate(udb)
        rc = cmd_candidate_analysis(self._ns(db_path, tmp_path / "nothing"))
        assert rc == 2
        assert "no preflight report" in capsys.readouterr().err

    def test_exit_three_when_live_read_fails(self, tmp_path, reports_dir, capsys):
        db_path = str(tmp_path / "c.db")
        with UnifiedDatabase(db_path) as udb:
            _insert_candidate(udb)
        ns = self._ns(db_path, reports_dir, no_live=False)
        ns.github = FakeGitHubFacade(fail_on="repo_metadata")
        rc = cmd_candidate_analysis(ns)
        assert rc == 3
        assert "--no-live" in capsys.readouterr().err

    def test_json_format_has_section_keys(self, tmp_path, reports_dir, capsys):
        db_path = str(tmp_path / "c.db")
        with UnifiedDatabase(db_path) as udb:
            _insert_candidate(udb)
        rc = cmd_candidate_analysis(self._ns(db_path, reports_dir, format="json"))
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        for key in SECTION_KEYS:
            assert key in data

    def test_out_writes_file(self, tmp_path, reports_dir, capsys):
        db_path = str(tmp_path / "c.db")
        with UnifiedDatabase(db_path) as udb:
            _insert_candidate(udb)
        out = tmp_path / "nested" / "analysis.md"
        rc = cmd_candidate_analysis(self._ns(db_path, reports_dir, out=str(out)))
        assert rc == 0
        assert out.exists()
        assert "# Candidate Analysis" in out.read_text(encoding="utf-8")
        assert "analysis written" in capsys.readouterr().out
