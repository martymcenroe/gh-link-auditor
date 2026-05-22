"""Tests for bulk_scan.liveness (#230 — on_result persistence callback)."""

from __future__ import annotations

from unittest.mock import patch

from gh_link_auditor.bulk_scan import liveness


def _fake_probe(url: str) -> tuple[str, dict]:
    """Mock probe that returns a predictable result without hitting the network."""
    if url.endswith("/dead"):
        return url, {"status": "dead", "status_code": 404}
    if url.endswith("/error"):
        return url, {"status": "error", "error": "transport"}
    return url, {"status": "alive", "status_code": 200, "final_url": url}


class TestCheckUrlsBulkOnResult:
    """check_urls_bulk(on_result=...) — invoke callback per URL from main thread (#230)."""

    def test_callback_invoked_once_per_url(self) -> None:
        urls = ["https://a.test/", "https://b.test/dead", "https://c.test/error"]
        seen: list[tuple[str, dict]] = []
        with patch.object(liveness, "_probe_one", side_effect=_fake_probe):
            out = liveness.check_urls_bulk(urls, workers=2, on_result=lambda u, r: seen.append((u, r)))
        assert len(out) == 3
        assert {u for u, _ in seen} == set(urls)
        assert len(seen) == 3

    def test_callback_optional(self) -> None:
        urls = ["https://a.test/"]
        with patch.object(liveness, "_probe_one", side_effect=_fake_probe):
            out = liveness.check_urls_bulk(urls, workers=1)  # no on_result
        assert out == {"https://a.test/": {"status": "alive", "status_code": 200, "final_url": "https://a.test/"}}

    def test_empty_urls_does_not_invoke_callback(self) -> None:
        called: list[tuple[str, dict]] = []
        out = liveness.check_urls_bulk([], on_result=lambda u, r: called.append((u, r)))
        assert out == {}
        assert called == []

    def test_callback_receives_result_dict(self) -> None:
        urls = ["https://x.test/dead"]
        seen: list[tuple[str, dict]] = []
        with patch.object(liveness, "_probe_one", side_effect=_fake_probe):
            liveness.check_urls_bulk(urls, workers=1, on_result=lambda u, r: seen.append((u, r)))
        assert seen[0][0] == "https://x.test/dead"
        assert seen[0][1] == {"status": "dead", "status_code": 404}

    def test_callback_propagates_exception(self) -> None:
        """If callback raises, it bubbles up — tests that we're not swallowing errors silently."""
        urls = ["https://a.test/"]

        def boom(_u: str, _r: dict) -> None:
            raise RuntimeError("callback failed")

        with patch.object(liveness, "_probe_one", side_effect=_fake_probe):
            try:
                liveness.check_urls_bulk(urls, workers=1, on_result=boom)
            except RuntimeError as e:
                assert "callback failed" in str(e)
            else:
                raise AssertionError("expected RuntimeError to propagate")
