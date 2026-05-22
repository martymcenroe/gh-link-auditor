"""Tests for bulk_scan.runner.run_liveness — cache-first + crash-recovery (#230)."""

from __future__ import annotations

from unittest.mock import patch

from gh_link_auditor.bulk_scan import liveness, runner, storage
from gh_link_auditor.unified_db import UnifiedDatabase


def _seed_run_with_pending_urls(db: UnifiedDatabase, run_id: str, urls: list[str]) -> None:
    """Seed a run + bulk_scan_findings rows with method='pending' for each URL."""
    storage.create_run(db, run_id, len(urls), {})
    for i, url in enumerate(urls):
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


def _fake_probe(url: str) -> tuple[str, dict]:
    if url.endswith("/dead"):
        return url, {"status": "dead", "status_code": 404}
    return url, {"status": "alive", "status_code": 200, "final_url": url}


class TestRunLivenessPersistence:
    def test_first_run_probes_all_urls(self, tmp_path) -> None:
        urls = ["https://a.test/", "https://b.test/dead", "https://c.test/"]
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            _seed_run_with_pending_urls(db, "r1", urls)
            with patch.object(liveness, "_probe_one", side_effect=_fake_probe):
                out = runner.run_liveness(db, "r1")
            assert set(out.keys()) == set(urls)
            # Verify each was written to cache
            for u in urls:
                assert db.get_cached_url_check(u) is not None

    def test_second_run_uses_cache_only(self, tmp_path) -> None:
        """The whole point of #230 — resume skips already-probed URLs."""
        urls = ["https://a.test/", "https://b.test/dead", "https://c.test/"]
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            _seed_run_with_pending_urls(db, "r1", urls)
            with patch.object(liveness, "_probe_one", side_effect=_fake_probe) as p:
                runner.run_liveness(db, "r1")
                assert p.call_count == 3
                # Second call: every URL is cached; no probes
                p.reset_mock()
                out = runner.run_liveness(db, "r1")
                assert p.call_count == 0
                assert set(out.keys()) == set(urls)

    def test_crash_recovery_only_reprobes_misses(self, tmp_path) -> None:
        """Simulate: probe URLs 1-3, then crash. Resume probes only URLs 4-6."""
        all_urls = [f"https://{c}.test/" for c in "abcdef"]
        first_batch = all_urls[:3]
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            # Pre-seed cache with first batch (simulating completed-before-crash work)
            for u in first_batch:
                db.cache_url_check(u, http_status=200, final_url=u, ttl_hours=720)
            _seed_run_with_pending_urls(db, "r1", all_urls)
            with patch.object(liveness, "_probe_one", side_effect=_fake_probe) as p:
                out = runner.run_liveness(db, "r1")
                # Only the un-cached 3 URLs got fresh probes
                assert p.call_count == 3
                probed_urls = {call.args[0] for call in p.call_args_list}
                assert probed_urls == set(all_urls) - set(first_batch)
                # But the returned dict has ALL 6 results
                assert set(out.keys()) == set(all_urls)

    def test_empty_findings_returns_empty(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            storage.create_run(db, "r1", 0, {})
            out = runner.run_liveness(db, "r1")
            assert out == {}

    def test_cache_hit_result_shape_matches_fresh(self, tmp_path) -> None:
        """Downstream run_investigation only reads status_code; cache must return that shape."""
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            db.cache_url_check(
                "https://x.test/",
                http_status=404,
                final_url="https://x.test/final",
                is_bot_blocked=True,
                ttl_hours=720,
            )
            _seed_run_with_pending_urls(db, "r1", ["https://x.test/"])
            out = runner.run_liveness(db, "r1")
            r = out["https://x.test/"]
            assert r["status_code"] == 404
            assert r["final_url"] == "https://x.test/final"
            assert r["is_bot_blocked"] is True
            assert r["status"] == "dead"

    def test_alive_status_reconstructed_from_2xx(self, tmp_path) -> None:
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            db.cache_url_check("https://x.test/", http_status=200, ttl_hours=720)
            _seed_run_with_pending_urls(db, "r1", ["https://x.test/"])
            out = runner.run_liveness(db, "r1")
            assert out["https://x.test/"]["status"] == "alive"

    def test_persist_called_with_correct_ttl(self, tmp_path) -> None:
        """Persist callback must use the long bulk-scan TTL, not the legacy 24h."""
        urls = ["https://a.test/"]
        with UnifiedDatabase(str(tmp_path / "x.db")) as db:
            _seed_run_with_pending_urls(db, "r1", urls)
            with patch.object(liveness, "_probe_one", side_effect=_fake_probe):
                runner.run_liveness(db, "r1")
            row = db._conn.execute(
                "SELECT last_checked_at, expires_at FROM url_check_cache WHERE url = ?",
                ("https://a.test/",),
            ).fetchone()
            assert row is not None
            from datetime import datetime

            checked = datetime.fromisoformat(row["last_checked_at"])
            expires = datetime.fromisoformat(row["expires_at"])
            ttl_hours = (expires - checked).total_seconds() / 3600
            # Allow tolerance for clock-skew; must be the bulk TTL (720h), not the 24h legacy
            assert 700 < ttl_hours < 740, f"unexpected TTL: {ttl_hours}h"


class TestLivenessResultFromCache:
    """Direct unit tests for _liveness_result_from_cache reconstruction (#230)."""

    def test_2xx_is_alive(self) -> None:
        out = runner._liveness_result_from_cache({"http_status": 200})
        assert out["status"] == "alive"
        assert out["status_code"] == 200

    def test_4xx_is_dead(self) -> None:
        out = runner._liveness_result_from_cache({"http_status": 404})
        assert out["status"] == "dead"

    def test_5xx_is_dead(self) -> None:
        out = runner._liveness_result_from_cache({"http_status": 503})
        assert out["status"] == "dead"

    def test_none_status_is_dead(self) -> None:
        out = runner._liveness_result_from_cache({"http_status": None})
        assert out["status"] == "dead"
        assert out["status_code"] is None

    def test_bot_blocked_preserved(self) -> None:
        out = runner._liveness_result_from_cache({"http_status": 403, "is_bot_blocked": True})
        assert out["is_bot_blocked"] is True

    def test_final_url_preserved(self) -> None:
        out = runner._liveness_result_from_cache({"http_status": 200, "final_url": "https://moved.example/"})
        assert out["final_url"] == "https://moved.example/"
