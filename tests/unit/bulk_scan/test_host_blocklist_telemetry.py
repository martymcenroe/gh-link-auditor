"""Tests for ``gh_link_auditor.bulk_scan.host_blocklist_telemetry`` (#258)."""

from __future__ import annotations

from pathlib import Path

from gh_link_auditor.bulk_scan import host_blocklist_telemetry as hbt
from gh_link_auditor.bulk_scan import storage
from gh_link_auditor.unified_db import UnifiedDatabase


def _seed_findings(
    db: UnifiedDatabase,
    run_id: str,
    *,
    host: str,
    n: int,
    state: str,
    status: int | None = 404,
) -> None:
    """Insert n Stage-1 placeholder findings for `host` and set their
    investigation_state, plus seed url_check_cache with `status`."""
    storage.update_run_status(db, run_id, "investigating")
    for i in range(n):
        url = f"https://{host}/p{i}"
        storage.add_finding(
            db,
            run_id,
            f"owner/repo{i}",
            "README.md",
            1,
            url,
            candidate_url="",
            method="pending",
            tier=0,
            similarity_score=None,
            verified_live=False,
            confidence=0.0,
        )
        if status is not None:
            db.cache_url_check(url, http_status=status, final_url=url, is_bot_blocked=False)
    db._conn.execute(
        "UPDATE bulk_scan_findings SET investigation_state = ? WHERE run_id = ? AND method = 'pending'",
        (state, run_id),
    )
    db._conn.commit()


def test_zero_yield_host_surfaces_as_candidate(tmp_path: Path) -> None:
    """A host with all real investigations no-cand and >= MIN gets flagged."""
    db_path = str(tmp_path / "x.db")
    with UnifiedDatabase(db_path) as db:
        storage.create_run(db, "r1", 100, {})
        _seed_findings(db, "r1", host="zerohost.example", n=hbt.MIN_INVESTIGATIONS, state="investigated_no_candidate")
        buckets = hbt.derive_blocklist_candidates(db, "r1")

    candidates = buckets["candidates"]
    assert len(candidates) == 1
    assert candidates[0].host == "zerohost.example"
    assert candidates[0].real == hbt.MIN_INVESTIGATIONS
    assert candidates[0].with_cand == 0
    assert candidates[0].yield_rate == 0.0


def test_below_min_investigations_does_not_surface(tmp_path: Path) -> None:
    """A host with too few real investigations is excluded -- thin samples
    don't deserve a blocklist entry."""
    db_path = str(tmp_path / "x.db")
    with UnifiedDatabase(db_path) as db:
        storage.create_run(db, "r1", 100, {})
        _seed_findings(
            db, "r1", host="rarehost.example", n=hbt.MIN_INVESTIGATIONS - 1, state="investigated_no_candidate"
        )
        buckets = hbt.derive_blocklist_candidates(db, "r1")

    assert buckets["candidates"] == []


def test_high_yield_host_does_not_surface(tmp_path: Path) -> None:
    """Hosts where Stage 3 succeeded should not get blocklisted -- they
    produce real PR candidates."""
    db_path = str(tmp_path / "x.db")
    with UnifiedDatabase(db_path) as db:
        storage.create_run(db, "r1", 100, {})
        # 30 with-candidate findings -> 100% yield, not a blocklist candidate
        _seed_findings(db, "r1", host="goodhost.example", n=hbt.MIN_INVESTIGATIONS, state="investigated_with_candidate")
        buckets = hbt.derive_blocklist_candidates(db, "r1")

    assert buckets["candidates"] == []
    # Should NOT appear in near-miss either (100% yield is far above 5%)
    assert buckets["near_misses"] == []


def test_near_miss_band_surfaces_separately(tmp_path: Path) -> None:
    """A host with 2-4% yield is in the near-miss band, not the recommended list."""
    db_path = str(tmp_path / "x.db")
    with UnifiedDatabase(db_path) as db:
        storage.create_run(db, "r1", 100, {})
        # Seed 50 findings: 1 with-cand, 49 no-cand -> 2% yield
        # First create them all as no-cand:
        _seed_findings(db, "r1", host="nearhost.example", n=50, state="investigated_no_candidate")
        # Flip one to with-candidate
        db._conn.execute(
            "UPDATE bulk_scan_findings SET investigation_state = 'investigated_with_candidate' "
            "WHERE run_id = 'r1' AND dead_url = 'https://nearhost.example/p0'"
        )
        db._conn.commit()
        buckets = hbt.derive_blocklist_candidates(db, "r1")

    assert buckets["candidates"] == []  # 2% > 1% -> not in recommended
    assert len(buckets["near_misses"]) == 1
    assert buckets["near_misses"][0].host == "nearhost.example"
    assert 0.01 < buckets["near_misses"][0].yield_rate <= 0.05


def test_already_blocklisted_host_is_filtered_out(tmp_path: Path) -> None:
    """The report only surfaces NEW candidates -- already-blocklisted hosts
    shouldn't re-appear in the recommended list every run."""
    db_path = str(tmp_path / "x.db")
    with UnifiedDatabase(db_path) as db:
        storage.create_run(db, "r1", 100, {})
        # medium.com is in ALWAYS_ALIVE_DOMAINS (per #358)
        _seed_findings(db, "r1", host="medium.com", n=hbt.MIN_INVESTIGATIONS, state="investigated_no_candidate")
        buckets = hbt.derive_blocklist_candidates(db, "r1")

    assert buckets["candidates"] == []
    # The host is in `all` for diagnostics, just not in `candidates`/`near_misses`
    assert any(r.host == "medium.com" for r in buckets["all"])


def test_subdomain_of_blocklisted_root_is_filtered_out(tmp_path: Path) -> None:
    """Subdomain matching is consistent with is_always_alive_domain."""
    db_path = str(tmp_path / "x.db")
    with UnifiedDatabase(db_path) as db:
        storage.create_run(db, "r1", 100, {})
        _seed_findings(db, "r1", host="english.medium.com", n=hbt.MIN_INVESTIGATIONS, state="investigated_no_candidate")
        buckets = hbt.derive_blocklist_candidates(db, "r1")

    assert buckets["candidates"] == []


def test_write_candidates_report_emits_markdown(tmp_path: Path) -> None:
    """The on-disk report has the expected sections and the candidate host name."""
    db_path = str(tmp_path / "x.db")
    out_path = tmp_path / "out.md"
    with UnifiedDatabase(db_path) as db:
        storage.create_run(db, "r1", 100, {})
        _seed_findings(
            db, "r1", host="another-zero.example", n=hbt.MIN_INVESTIGATIONS, state="investigated_no_candidate"
        )
        result_path = hbt.write_candidates_report(db, "r1", db_path=db_path, out_path=out_path)

    assert result_path == out_path
    body = out_path.read_text(encoding="utf-8")
    assert "# Host blocklist candidates from `r1`" in body
    assert "another-zero.example" in body
    assert "## Hosts recommended for blocklist" in body
    assert "## Near-miss hosts (1%-5% yield)" in body


def test_pending_findings_count_but_dont_count_as_real(tmp_path: Path) -> None:
    """Pending (un-investigated) findings should not contribute to real_investigations."""
    db_path = str(tmp_path / "x.db")
    with UnifiedDatabase(db_path) as db:
        storage.create_run(db, "r1", 100, {})
        _seed_findings(db, "r1", host="pendinghost.example", n=hbt.MIN_INVESTIGATIONS, state="pending")
        buckets = hbt.derive_blocklist_candidates(db, "r1")

    # All pending -> 0 real -> doesn't meet MIN_INVESTIGATIONS -> not a candidate
    assert buckets["candidates"] == []


def test_skipped_alive_findings_dont_count_as_real(tmp_path: Path) -> None:
    """skipped_alive means Stage 3 didn't investigate (URL was 2xx); should
    not count toward real_investigations or the wasted figure."""
    db_path = str(tmp_path / "x.db")
    with UnifiedDatabase(db_path) as db:
        storage.create_run(db, "r1", 100, {})
        _seed_findings(db, "r1", host="alivehost.example", n=hbt.MIN_INVESTIGATIONS, state="skipped_alive")
        buckets = hbt.derive_blocklist_candidates(db, "r1")

    assert buckets["candidates"] == []
