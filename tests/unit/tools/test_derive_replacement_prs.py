"""Tests for tools/derive_replacement_prs.py (#273)."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

import pytest

from gh_link_auditor.metrics.models import PROutcome
from gh_link_auditor.unified_db import UnifiedDatabase

# tools/ is an implicit namespace package (no __init__.py) — Python 3.3+
# finds it when the project root is on sys.path (which pyproject.toml's
# [tool.pytest.ini_options] pythonpath = [".", "src"] arranges).
from tools import derive_replacement_prs as mod

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_row(**overrides) -> dict:
    base = {
        "id": 1,
        "run_id": "test-run",
        "repo_full_name": "owner/repo",
        "source_file": "README.md",
        "line_number": 5,
        "dead_url": "https://old.example.com",
        "candidate_url": "https://new.example.com",
        "method": "github_api_redirect",
        "tier": 1,
        "similarity_score": 1.0,
        "verified_live": 1,
        "confidence": 1.0,
        "surfaced": 0,
        "created_at": "2026-05-23T15:00:00+00:00",
        "investigation_state": "derived_candidate",
    }
    base.update(overrides)
    return base


def _insert_finding(udb: UnifiedDatabase, **overrides) -> int:
    row = _make_row(**overrides)
    cur = udb._conn.execute(
        """INSERT INTO bulk_scan_findings
           (run_id, repo_full_name, source_file, line_number, dead_url, candidate_url,
            method, tier, similarity_score, verified_live, confidence, surfaced,
            created_at, investigation_state)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            row["run_id"],
            row["repo_full_name"],
            row["source_file"],
            row["line_number"],
            row["dead_url"],
            row["candidate_url"],
            row["method"],
            row["tier"],
            row["similarity_score"],
            row["verified_live"],
            row["confidence"],
            row["surfaced"],
            row["created_at"],
            row["investigation_state"],
        ),
    )
    udb._conn.commit()
    return cur.lastrowid


def _make_args(**overrides) -> argparse.Namespace:
    defaults = {
        "db": "/tmp/x",
        "run_id": None,
        "method": None,
        "min_confidence": None,
        "repo": None,
        "max_prs": 10,
        "auto_approve": True,
        "dry_run": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------


class TestRowToFix:
    def test_basic(self):
        fix = mod._row_to_fix(_make_row())
        assert fix == {
            "source_file": "README.md",
            "original_url": "https://old.example.com",
            "replacement_url": "https://new.example.com",
            "unified_diff": "",
        }


class TestRowToVerdict:
    def test_basic(self):
        v = mod._row_to_verdict(_make_row())
        assert v["dead_link"]["url"] == "https://old.example.com"
        assert v["dead_link"]["source_file"] == "README.md"
        assert v["dead_link"]["line_number"] == 5
        assert v["candidate"]["url"] == "https://new.example.com"
        assert v["candidate"]["source"] == "github_api_redirect"
        assert v["candidate"]["tier"] == 1
        assert v["confidence"] == 1.0
        assert v["approved"] is True

    def test_null_line_number(self):
        v = mod._row_to_verdict(_make_row(line_number=None))
        assert v["dead_link"]["line_number"] == 0

    def test_null_confidence_defaults_to_one(self):
        v = mod._row_to_verdict(_make_row(confidence=None))
        assert v["confidence"] == 1.0

    def test_null_tier_defaults_to_one(self):
        v = mod._row_to_verdict(_make_row(tier=None))
        assert v["candidate"]["tier"] == 1

    def test_null_method_blank(self):
        v = mod._row_to_verdict(_make_row(method=None))
        assert v["candidate"]["source"] == ""


class TestIsSafelyReplaceable:
    def test_clean_url_pair_safe(self):
        ok, reason = mod._is_safely_replaceable(
            "https://old.example.com/page",
            "https://new.example.com/page",
        )
        assert ok is True
        assert reason == ""

    def test_url_mutation_safe(self):
        # index.htm → / — candidate is NOT a substring of dead (the / changes it)
        ok, reason = mod._is_safely_replaceable(
            "https://sumo.dlr.de/docs/Installing/index.htm",
            "https://sumo.dlr.de/docs/Installing/",
        )
        assert ok is True

    def test_github_rename_safe(self):
        ok, reason = mod._is_safely_replaceable(
            "https://github.com/volcengine/verl/blob/main/docs/README_vllm0.7.md",
            "https://github.com/verl-project/verl/blob/main/docs/README_vllm0.7.md",
        )
        assert ok is True

    def test_balanced_wikipedia_paren_safe(self):
        # Real Wikipedia URLs with parens like Measure_(mathematics) are fine
        ok, reason = mod._is_safely_replaceable(
            "https://en.wikipedia.org/wiki/Measure_(mathematics%29)",  # bad encoding
            "https://en.wikipedia.org/wiki/Measure_(mathematics)",  # fixed encoding
        )
        assert ok is True

    def test_unbalanced_paren_rejected(self):
        # The Okapi_BM25)'s case — extractor caught a closing paren from markdown
        ok, reason = mod._is_safely_replaceable(
            "https://en.wikipedia.org/wiki/Okapi_BM25)'s",
            "https://en.wikipedia.org/wiki/Okapi_BM25",
        )
        assert ok is False
        assert reason == "unbalanced_paren"

    def test_unbalanced_paren_with_trailing_letters_rejected(self):
        ok, reason = mod._is_safely_replaceable(
            "https://en.wikipedia.org/wiki/Remote_procedure_call)is",
            "https://en.wikipedia.org/wiki/Remote_procedure_call",
        )
        assert ok is False
        assert reason == "unbalanced_paren"

    def test_candidate_prefix_with_quote_suffix_rejected(self):
        # No unbalanced paren but trailing quote — markdown-junk suffix
        ok, reason = mod._is_safely_replaceable(
            'https://example.com/page"',
            "https://example.com/page",
        )
        assert ok is False
        assert reason == "dead_url_suffix_has_markdown_chars"

    def test_candidate_prefix_with_space_suffix_rejected(self):
        ok, reason = mod._is_safely_replaceable(
            "https://example.com/page extra",
            "https://example.com/page",
        )
        assert ok is False
        assert reason == "dead_url_suffix_has_markdown_chars"

    def test_candidate_prefix_with_url_path_suffix_safe(self):
        # url_mutation case: candidate ends in /, dead has more path. The
        # suffix is URL-valid chars only — legitimate URL change.
        ok, reason = mod._is_safely_replaceable(
            "https://example.com/docs/foo/index.html",
            "https://example.com/docs/foo/",
        )
        assert ok is True

    def test_substring_in_middle_not_rejected(self):
        # candidate appears INSIDE dead but not as a prefix — different URL
        ok, reason = mod._is_safely_replaceable(
            "https://prefix/example.com/page/suffix",
            "https://example.com/page",
        )
        assert ok is True

    def test_identical_urls_safe(self):
        # Edge case: dead == candidate is treated as safe (no-op replace)
        ok, _ = mod._is_safely_replaceable("https://x.com/a", "https://x.com/a")
        assert ok is True


class TestGroupByRepo:
    def test_single_repo(self):
        rows = [_make_row(id=1), _make_row(id=2)]
        grouped = mod._group_by_repo(rows)
        assert list(grouped) == ["owner/repo"]
        assert len(grouped["owner/repo"]) == 2

    def test_multiple_repos(self):
        rows = [
            _make_row(id=1, repo_full_name="a/b"),
            _make_row(id=2, repo_full_name="c/d"),
            _make_row(id=3, repo_full_name="a/b"),
        ]
        grouped = mod._group_by_repo(rows)
        assert set(grouped) == {"a/b", "c/d"}
        assert len(grouped["a/b"]) == 2
        assert len(grouped["c/d"]) == 1


class TestBuildState:
    def test_shape(self):
        fixes = [{"source_file": "f.md", "original_url": "o", "replacement_url": "n", "unified_diff": ""}]
        state = mod._build_state("owner/repo", fixes, [], "/tmp/db", dry_run=False)
        assert state["repo_owner"] == "owner"
        assert state["repo_name_short"] == "repo"
        assert state["target_type"] == "url"
        assert state["target"] == "https://github.com/owner/repo"
        assert state["fixes"] == fixes
        assert state["dry_run"] is False
        assert state["db_path"] == "/tmp/db"

    def test_owner_with_slash_in_repo_name(self):
        # GitHub repo names cannot contain slashes, but the partition logic
        # should still handle that edge case predictably.
        state = mod._build_state("owner/repo-with-dash", [], [], "/tmp/db", dry_run=False)
        assert state["repo_owner"] == "owner"
        assert state["repo_name_short"] == "repo-with-dash"


# ---------------------------------------------------------------------------
# DB queries
# ---------------------------------------------------------------------------


class TestLoadUnsurfacedCandidates:
    def test_skip_surfaced(self, db_path):
        with UnifiedDatabase(db_path) as udb:
            _insert_finding(udb, surfaced=0)
            _insert_finding(udb, surfaced=1)
            rows = mod._load_unsurfaced_candidates(udb)
        assert len(rows) == 1
        assert rows[0]["surfaced"] == 0

    def test_skip_non_derived(self, db_path):
        with UnifiedDatabase(db_path) as udb:
            _insert_finding(udb, investigation_state="derived_candidate")
            _insert_finding(udb, investigation_state="pending")
            rows = mod._load_unsurfaced_candidates(udb)
        assert len(rows) == 1
        assert rows[0]["investigation_state"] == "derived_candidate"

    def test_run_id_filter(self, db_path):
        with UnifiedDatabase(db_path) as udb:
            _insert_finding(udb, run_id="run-A")
            _insert_finding(udb, run_id="run-B")
            rows = mod._load_unsurfaced_candidates(udb, run_id="run-A")
        assert len(rows) == 1
        assert rows[0]["run_id"] == "run-A"

    def test_method_filter(self, db_path):
        with UnifiedDatabase(db_path) as udb:
            _insert_finding(udb, method="github_api_redirect")
            _insert_finding(udb, method="url_mutation")
            rows = mod._load_unsurfaced_candidates(udb, method="github_api_redirect")
        assert len(rows) == 1
        assert rows[0]["method"] == "github_api_redirect"

    def test_min_confidence_filter(self, db_path):
        with UnifiedDatabase(db_path) as udb:
            _insert_finding(udb, confidence=0.5)
            _insert_finding(udb, confidence=0.95)
            rows = mod._load_unsurfaced_candidates(udb, min_confidence=0.9)
        assert len(rows) == 1
        assert rows[0]["confidence"] == 0.95

    def test_repo_filter(self, db_path):
        with UnifiedDatabase(db_path) as udb:
            _insert_finding(udb, repo_full_name="a/b")
            _insert_finding(udb, repo_full_name="c/d")
            rows = mod._load_unsurfaced_candidates(udb, repo="a/b")
        assert len(rows) == 1


class TestMarkSurfaced:
    def test_mark_multiple(self, db_path):
        with UnifiedDatabase(db_path) as udb:
            id1 = _insert_finding(udb)
            id2 = _insert_finding(udb)
            mod._mark_surfaced(udb, [id1, id2])
            r1 = udb._conn.execute("SELECT surfaced FROM bulk_scan_findings WHERE id = ?", (id1,)).fetchone()
            r2 = udb._conn.execute("SELECT surfaced FROM bulk_scan_findings WHERE id = ?", (id2,)).fetchone()
        assert r1["surfaced"] == 1
        assert r2["surfaced"] == 1

    def test_empty_noop(self, db_path):
        with UnifiedDatabase(db_path) as udb:
            mod._mark_surfaced(udb, [])


class TestHasOpenPr:
    def test_no_pr(self, db_path):
        with UnifiedDatabase(db_path) as udb:
            assert mod._has_open_pr(udb, "owner/repo") is False

    def test_has_open(self, db_path):
        with UnifiedDatabase(db_path) as udb:
            udb.record_pr_outcome(
                PROutcome(
                    repo_full_name="owner/repo",
                    pr_url="https://github.com/owner/repo/pull/1",
                    submitted_at=datetime.now(timezone.utc),
                    status="open",
                )
            )
            assert mod._has_open_pr(udb, "owner/repo") is True

    def test_closed_pr_does_not_block(self, db_path):
        with UnifiedDatabase(db_path) as udb:
            udb.record_pr_outcome(
                PROutcome(
                    repo_full_name="owner/repo",
                    pr_url="https://github.com/owner/repo/pull/1",
                    submitted_at=datetime.now(timezone.utc),
                    status="closed",
                )
            )
            assert mod._has_open_pr(udb, "owner/repo") is False


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


class TestPromptYesNoStop:
    def test_yes(self):
        assert mod._prompt_yes_no_stop(input_fn=lambda _: "y") == "y"

    def test_no(self):
        assert mod._prompt_yes_no_stop(input_fn=lambda _: "n") == "n"

    def test_stop(self):
        assert mod._prompt_yes_no_stop(input_fn=lambda _: "s") == "s"

    def test_full_words(self):
        assert mod._prompt_yes_no_stop(input_fn=lambda _: "yes") == "y"
        assert mod._prompt_yes_no_stop(input_fn=lambda _: "stop") == "s"

    def test_invalid_reprompts(self):
        responses = iter(["maybe", "y"])
        result = mod._prompt_yes_no_stop(input_fn=lambda _: next(responses))
        assert result == "y"


# ---------------------------------------------------------------------------
# End-to-end with fake N6
# ---------------------------------------------------------------------------


class TestDeriveAndSubmit:
    def test_submits_basic(self, db_path):
        with UnifiedDatabase(db_path) as udb:
            _insert_finding(udb, repo_full_name="alpha/beta", source_file="a.md")
            _insert_finding(udb, repo_full_name="alpha/beta", source_file="b.md")

        def fake_n6(state):
            state["pr_url"] = "https://github.com/alpha/beta/pull/42"
            state["pr_number"] = 42
            return state

        result = mod.derive_and_submit(_make_args(db=db_path), n6_fn=fake_n6)
        assert len(result["submitted"]) == 1
        assert result["submitted"][0] == ("alpha/beta", "https://github.com/alpha/beta/pull/42")

        with UnifiedDatabase(db_path) as udb:
            rows = udb._conn.execute("SELECT surfaced FROM bulk_scan_findings").fetchall()
            assert all(r["surfaced"] == 1 for r in rows)
            outcome = udb._conn.execute("SELECT pr_url FROM pr_outcomes").fetchone()
            assert outcome["pr_url"] == "https://github.com/alpha/beta/pull/42"

    def test_skips_blacklisted(self, db_path):
        with UnifiedDatabase(db_path) as udb:
            _insert_finding(udb, repo_full_name="bad/repo")
            udb.add_to_blacklist(repo_url="https://github.com/bad/repo", reason="test")

        n6_calls = []

        def fake_n6(state):
            n6_calls.append(state)
            return state

        result = mod.derive_and_submit(_make_args(db=db_path), n6_fn=fake_n6)
        assert n6_calls == []
        assert ("bad/repo", "blacklisted") in result["skipped"]

    def test_skips_existing_open_pr(self, db_path):
        with UnifiedDatabase(db_path) as udb:
            _insert_finding(udb, repo_full_name="open/pr")
            udb.record_pr_outcome(
                PROutcome(
                    repo_full_name="open/pr",
                    pr_url="https://github.com/open/pr/pull/1",
                    submitted_at=datetime.now(timezone.utc),
                    status="open",
                )
            )

        n6_calls = []

        def fake_n6(state):
            n6_calls.append(state)
            return state

        result = mod.derive_and_submit(_make_args(db=db_path), n6_fn=fake_n6)
        assert n6_calls == []
        assert ("open/pr", "open_pr_exists") in result["skipped"]

    def test_n6_error_recorded(self, db_path):
        with UnifiedDatabase(db_path) as udb:
            _insert_finding(udb, repo_full_name="err/repo")

        def fake_n6(state):
            state["errors"] = ["fork failed"]
            return state

        result = mod.derive_and_submit(_make_args(db=db_path), n6_fn=fake_n6)
        assert len(result["errors"]) == 1
        assert result["errors"][0][0] == "err/repo"
        with UnifiedDatabase(db_path) as udb:
            row = udb._conn.execute(
                "SELECT surfaced FROM bulk_scan_findings WHERE repo_full_name = ?",
                ("err/repo",),
            ).fetchone()
            assert row["surfaced"] == 0

    def test_n6_exception_caught(self, db_path):
        with UnifiedDatabase(db_path) as udb:
            _insert_finding(udb, repo_full_name="boom/repo")

        def fake_n6(state):
            raise RuntimeError("network down")

        result = mod.derive_and_submit(_make_args(db=db_path), n6_fn=fake_n6)
        assert len(result["errors"]) == 1
        assert "RuntimeError" in result["errors"][0][1]

    def test_max_prs_cap(self, db_path):
        with UnifiedDatabase(db_path) as udb:
            _insert_finding(udb, repo_full_name="a/1")
            _insert_finding(udb, repo_full_name="a/2")
            _insert_finding(udb, repo_full_name="a/3")

        def fake_n6(state):
            state["pr_url"] = f"https://github.com/{state['repo_owner']}/{state['repo_name_short']}/pull/1"
            return state

        result = mod.derive_and_submit(_make_args(db=db_path, max_prs=2), n6_fn=fake_n6)
        assert len(result["submitted"]) == 2

    def test_dry_run_no_submission(self, db_path):
        with UnifiedDatabase(db_path) as udb:
            _insert_finding(udb, repo_full_name="dry/run")

        n6_calls = []

        def fake_n6(state):
            n6_calls.append(state)
            return state

        result = mod.derive_and_submit(_make_args(db=db_path, dry_run=True), n6_fn=fake_n6)
        assert n6_calls == []
        assert result["submitted"] == []
        assert ("dry/run", "dry_run") in result["skipped"]
        with UnifiedDatabase(db_path) as udb:
            row = udb._conn.execute("SELECT surfaced FROM bulk_scan_findings").fetchone()
            assert row["surfaced"] == 0

    def test_interactive_decline(self, db_path):
        with UnifiedDatabase(db_path) as udb:
            _insert_finding(udb, repo_full_name="ask/me")

        n6_calls = []

        def fake_n6(state):
            n6_calls.append(state)
            return state

        result = mod.derive_and_submit(
            _make_args(db=db_path, auto_approve=False),
            n6_fn=fake_n6,
            input_fn=lambda _: "n",
        )
        assert n6_calls == []
        assert ("ask/me", "operator_declined") in result["skipped"]

    def test_interactive_stop(self, db_path):
        with UnifiedDatabase(db_path) as udb:
            _insert_finding(udb, repo_full_name="x/1")
            _insert_finding(udb, repo_full_name="y/2")

        n6_calls = []

        def fake_n6(state):
            n6_calls.append(state)
            state["pr_url"] = "x"
            return state

        # Operator types 's' on the first repo — second repo never prompted.
        result = mod.derive_and_submit(
            _make_args(db=db_path, auto_approve=False),
            n6_fn=fake_n6,
            input_fn=lambda _: "s",
        )
        assert n6_calls == []
        assert any(reason == "stop_requested" for _, reason in result["skipped"])

    def test_n6_no_pr_url_recorded_as_error(self, db_path):
        with UnifiedDatabase(db_path) as udb:
            _insert_finding(udb, repo_full_name="silent/repo")

        def fake_n6(state):
            # n6 returns without pr_url and without errors — pathological
            return state

        result = mod.derive_and_submit(_make_args(db=db_path), n6_fn=fake_n6)
        assert len(result["errors"]) == 1
        assert "no pr_url" in result["errors"][0][1]

    def test_skips_repo_with_only_unsafe_candidates(self, db_path):
        # All findings for this repo have unbalanced parens — N6 must NOT be
        # called; the repo gets logged as all_candidates_unsafe.
        with UnifiedDatabase(db_path) as udb:
            _insert_finding(
                udb,
                repo_full_name="unsafe/repo",
                dead_url="https://en.wikipedia.org/wiki/Foo)'s",
                candidate_url="https://en.wikipedia.org/wiki/Foo",
            )

        n6_calls = []

        def fake_n6(state):
            n6_calls.append(state)
            return state

        result = mod.derive_and_submit(_make_args(db=db_path), n6_fn=fake_n6)
        assert n6_calls == []
        assert ("unsafe/repo", "all_candidates_unsafe") in result["skipped"]

    def test_partial_unsafe_keeps_safe_candidates(self, db_path):
        # Same repo has one safe + one unsafe candidate. N6 should be called
        # with ONLY the safe one.
        with UnifiedDatabase(db_path) as udb:
            _insert_finding(
                udb,
                repo_full_name="mixed/repo",
                source_file="a.md",
                dead_url="https://en.wikipedia.org/wiki/Foo)'s",
                candidate_url="https://en.wikipedia.org/wiki/Foo",
            )
            _insert_finding(
                udb,
                repo_full_name="mixed/repo",
                source_file="b.md",
                dead_url="https://docs.example.com/old/index.html",
                candidate_url="https://docs.example.com/new/index.html",
            )

        captured = []

        def fake_n6(state):
            captured.append([fix["source_file"] for fix in state["fixes"]])
            state["pr_url"] = "https://github.com/mixed/repo/pull/1"
            return state

        result = mod.derive_and_submit(_make_args(db=db_path), n6_fn=fake_n6)
        assert len(result["submitted"]) == 1
        # Only the safe fix made it into the PR
        assert captured == [["b.md"]]


# ---------------------------------------------------------------------------
# Output rendering + CLI surface
# ---------------------------------------------------------------------------


class TestShowPreview:
    def test_renders_without_error(self, capsys):
        row = _make_row()
        fix = mod._row_to_fix(row)
        mod._show_preview("owner/repo", [fix], [row])
        out = capsys.readouterr().out
        assert "owner/repo" in out
        assert "1 fix" in out
        assert row["dead_url"] in out
        assert row["candidate_url"] in out

    def test_pluralizes(self, capsys):
        rows = [_make_row(), _make_row(id=2, source_file="b.md")]
        fixes = mod._rows_to_fixes(rows)
        mod._show_preview("owner/repo", fixes, rows)
        out = capsys.readouterr().out
        assert "2 fixes" in out

    def test_meta_skipped_when_null(self, capsys):
        row = _make_row(
            method=None,
            confidence=None,
            similarity_score=None,
            verified_live=0,
            line_number=None,
        )
        fix = mod._row_to_fix(row)
        mod._show_preview("o/r", [fix], [row])
        # No crash — meta line skipped because all metadata is null/zero.


class TestPrintSummary:
    def test_renders_all_sections(self, capsys):
        result = {
            "submitted": [("a/b", "https://github.com/a/b/pull/1")],
            "skipped": [("c/d", "blacklisted")],
            "errors": [("e/f", "boom")],
        }
        mod._print_summary(result)
        out = capsys.readouterr().out
        assert "submitted: 1" in out
        assert "https://github.com/a/b/pull/1" in out
        assert "skipped:   1" in out
        assert "blacklisted" in out
        assert "errors:    1" in out
        assert "boom" in out

    def test_no_errors_section_when_empty(self, capsys):
        result = {"submitted": [], "skipped": [], "errors": []}
        mod._print_summary(result)
        out = capsys.readouterr().out
        # No "errors:" line when zero errors
        assert "errors:" not in out


class TestBuildParser:
    def test_defaults(self):
        args = mod._build_parser().parse_args([])
        assert args.run_id is None
        assert args.method is None
        assert args.min_confidence is None
        assert args.repo is None
        assert args.max_prs == 10
        assert args.auto_approve is False
        assert args.dry_run is False
        assert args.campaign_allowed is False

    def test_explicit_flags(self):
        args = mod._build_parser().parse_args(
            [
                "--db",
                "/tmp/x.db",
                "--run-id",
                "bulk-X",
                "--method",
                "github_api_redirect",
                "--min-confidence",
                "0.9",
                "--repo",
                "o/r",
                "--max-prs",
                "5",
                "--auto-approve",
                "--dry-run",
                "--campaign-allowed",
            ]
        )
        assert args.db == "/tmp/x.db"
        assert args.run_id == "bulk-X"
        assert args.method == "github_api_redirect"
        assert args.min_confidence == 0.9
        assert args.repo == "o/r"
        assert args.max_prs == 5
        assert args.auto_approve is True
        assert args.dry_run is True
        assert args.campaign_allowed is True


class TestMain:
    def test_main_dry_run_exit_zero(self, db_path, monkeypatch):
        with UnifiedDatabase(db_path) as udb:
            _insert_finding(udb, repo_full_name="m/m")
        rc = mod.main(["--db", db_path, "--dry-run", "--campaign-allowed"])
        assert rc == 0

    def test_main_no_candidates(self, db_path):
        # Empty DB — main returns 0, prints summary with zeros
        with UnifiedDatabase(db_path):
            pass
        rc = mod.main(["--db", db_path, "--auto-approve", "--campaign-allowed"])
        assert rc == 0

    def test_main_refuses_without_campaign_allowed(self, db_path, capsys):
        """#278: without --campaign-allowed the tool must exit 2 with a pause message."""
        rc = mod.main(["--db", db_path, "--dry-run"])
        captured = capsys.readouterr()
        assert rc == 2
        assert "--campaign-allowed flag is required" in captured.err
        assert "#278" in captured.err

    def test_main_pause_message_mentions_flag_and_issue(self):
        """The pause-message constant points the operator at both the flag and the issue."""
        assert "--campaign-allowed" in mod._CAMPAIGN_PAUSED_MESSAGE
        assert "#278" in mod._CAMPAIGN_PAUSED_MESSAGE
        assert "scrub" in mod._CAMPAIGN_PAUSED_MESSAGE.lower()
