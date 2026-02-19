"""Tests for pipeline state management.

See LLD #22 §10.0 T230: State persistence verified.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from gh_link_auditor.pipeline.state import (
    CostRecord,
    DeadLink,
    FixPatch,
    ReplacementCandidate,
    Verdict,
    create_initial_state,
    load_state,
    persist_state,
)


class TestCreateInitialState:
    """Tests for create_initial_state()."""

    def test_returns_pipeline_state(self) -> None:
        state = create_initial_state(target="https://github.com/org/repo")
        assert isinstance(state, dict)

    def test_sets_target(self) -> None:
        state = create_initial_state(target="https://github.com/org/repo")
        assert state["target"] == "https://github.com/org/repo"

    def test_default_max_links(self) -> None:
        state = create_initial_state(target="t")
        assert state["max_links"] == 50

    def test_default_max_cost(self) -> None:
        state = create_initial_state(target="t")
        assert state["max_cost_usd"] == 5.00

    def test_default_confidence_threshold(self) -> None:
        state = create_initial_state(target="t")
        assert state["confidence_threshold"] == 0.8

    def test_default_dry_run_false(self) -> None:
        state = create_initial_state(target="t")
        assert state["dry_run"] is False

    def test_default_verbose_false(self) -> None:
        state = create_initial_state(target="t")
        assert state["verbose"] is False

    def test_custom_max_links(self) -> None:
        state = create_initial_state(target="t", max_links=100)
        assert state["max_links"] == 100

    def test_custom_max_cost(self) -> None:
        state = create_initial_state(target="t", max_cost_usd=10.0)
        assert state["max_cost_usd"] == 10.0

    def test_generates_uuid_run_id(self) -> None:
        state = create_initial_state(target="t")
        uuid.UUID(state["run_id"])  # Raises ValueError if invalid

    def test_unique_run_ids(self) -> None:
        s1 = create_initial_state(target="t")
        s2 = create_initial_state(target="t")
        assert s1["run_id"] != s2["run_id"]

    def test_default_db_path(self) -> None:
        state = create_initial_state(target="t")
        assert "state.db" in state["db_path"]
        assert ".ghla" in state["db_path"]

    def test_custom_db_path(self) -> None:
        state = create_initial_state(target="t", db_path="/tmp/test.db")
        assert state["db_path"] == "/tmp/test.db"

    def test_empty_initial_collections(self) -> None:
        state = create_initial_state(target="t")
        assert state["doc_files"] == []
        assert state["dead_links"] == []
        assert state["candidates"] == {}
        assert state["verdicts"] == []
        assert state["reviewed_verdicts"] == []
        assert state["fixes"] == []
        assert state["cost_records"] == []
        assert state["errors"] == []

    def test_initial_booleans(self) -> None:
        state = create_initial_state(target="t")
        assert state["scan_complete"] is False
        assert state["circuit_breaker_triggered"] is False
        assert state["cost_limit_reached"] is False
        assert state["partial_results"] is False

    def test_initial_cost_zero(self) -> None:
        state = create_initial_state(target="t")
        assert state["total_cost_usd"] == 0.0

    def test_target_type_empty(self) -> None:
        state = create_initial_state(target="t")
        assert state["target_type"] == ""

    def test_repo_name_empty(self) -> None:
        state = create_initial_state(target="t")
        assert state["repo_name"] == ""


class TestPersistState:
    """Tests for persist_state()."""

    def test_creates_state_file(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "state.db")
        state = create_initial_state(target="t", db_path=db_path)
        persist_state(state, "n0")
        state_file = tmp_path / f"{state['run_id']}.json"
        assert state_file.exists()

    def test_state_file_contains_run_id(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "state.db")
        state = create_initial_state(target="t", db_path=db_path)
        persist_state(state, "n0")
        state_file = tmp_path / f"{state['run_id']}.json"
        data = json.loads(state_file.read_text())
        assert data["run_id"] == state["run_id"]

    def test_state_file_contains_last_node(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "state.db")
        state = create_initial_state(target="t", db_path=db_path)
        persist_state(state, "n1")
        state_file = tmp_path / f"{state['run_id']}.json"
        data = json.loads(state_file.read_text())
        assert data["last_node"] == "n1"

    def test_state_file_contains_timestamp(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "state.db")
        state = create_initial_state(target="t", db_path=db_path)
        persist_state(state, "n0")
        state_file = tmp_path / f"{state['run_id']}.json"
        data = json.loads(state_file.read_text())
        assert "timestamp" in data

    def test_state_file_contains_full_state(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "state.db")
        state = create_initial_state(target="https://github.com/a/b", db_path=db_path)
        persist_state(state, "n0")
        state_file = tmp_path / f"{state['run_id']}.json"
        data = json.loads(state_file.read_text())
        assert data["state"]["target"] == "https://github.com/a/b"

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "sub" / "dir" / "state.db")
        state = create_initial_state(target="t", db_path=db_path)
        persist_state(state, "n0")
        state_file = tmp_path / "sub" / "dir" / f"{state['run_id']}.json"
        assert state_file.exists()

    def test_no_op_for_empty_db_path(self) -> None:
        state = create_initial_state(target="t")
        state["db_path"] = ""
        persist_state(state, "n0")  # Should not raise

    def test_overwrites_on_subsequent_nodes(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "state.db")
        state = create_initial_state(target="t", db_path=db_path)
        persist_state(state, "n0")
        state["scan_complete"] = True
        persist_state(state, "n1")
        state_file = tmp_path / f"{state['run_id']}.json"
        data = json.loads(state_file.read_text())
        assert data["last_node"] == "n1"
        assert data["state"]["scan_complete"] is True


class TestLoadState:
    """Tests for load_state()."""

    def test_round_trip(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "state.db")
        state = create_initial_state(target="https://github.com/a/b", db_path=db_path)
        persist_state(state, "n0")
        loaded = load_state(state["run_id"], db_path)
        assert loaded is not None
        assert loaded["target"] == "https://github.com/a/b"

    def test_returns_none_for_missing(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "state.db")
        result = load_state("nonexistent-id", db_path)
        assert result is None

    def test_preserves_all_fields(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "state.db")
        state = create_initial_state(target="t", db_path=db_path)
        state["dead_links"] = [
            DeadLink(
                url="https://example.com/broken",
                source_file="README.md",
                line_number=10,
                link_text="link",
                http_status=404,
                error_type="http_error",
            )
        ]
        persist_state(state, "n1")
        loaded = load_state(state["run_id"], db_path)
        assert loaded is not None
        assert len(loaded["dead_links"]) == 1
        assert loaded["dead_links"][0]["url"] == "https://example.com/broken"


class TestTypedDicts:
    """Tests for TypedDict correctness."""

    def test_dead_link_fields(self) -> None:
        dl = DeadLink(
            url="https://x.com",
            source_file="a.md",
            line_number=1,
            link_text="t",
            http_status=404,
            error_type="http_error",
        )
        assert dl["url"] == "https://x.com"
        assert dl["http_status"] == 404

    def test_dead_link_none_status(self) -> None:
        dl = DeadLink(
            url="https://x.com",
            source_file="a.md",
            line_number=1,
            link_text="t",
            http_status=None,
            error_type="dns_error",
        )
        assert dl["http_status"] is None

    def test_replacement_candidate_fields(self) -> None:
        rc = ReplacementCandidate(
            url="https://new.com",
            source="wayback",
            title="Title",
            snippet="snip",
        )
        assert rc["source"] == "wayback"

    def test_verdict_fields(self) -> None:
        dl = DeadLink(
            url="u", source_file="f", line_number=1,
            link_text="t", http_status=404, error_type="http_error",
        )
        v = Verdict(
            dead_link=dl,
            candidate=None,
            confidence=0.5,
            reasoning="no good match",
            approved=None,
        )
        assert v["confidence"] == 0.5
        assert v["approved"] is None

    def test_fix_patch_fields(self) -> None:
        fp = FixPatch(
            source_file="README.md",
            original_url="https://old.com",
            replacement_url="https://new.com",
            unified_diff="--- a\n+++ b",
        )
        assert fp["unified_diff"].startswith("---")

    def test_cost_record_fields(self) -> None:
        cr = CostRecord(
            node="n3",
            model="gpt-4o-mini",
            input_tokens=100,
            output_tokens=50,
            estimated_cost_usd=0.01,
            timestamp="2024-01-01T00:00:00Z",
        )
        assert cr["estimated_cost_usd"] == 0.01
