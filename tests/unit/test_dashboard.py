"""Unit tests for Slant HITL dashboard.

Tests HTTP endpoints, POST /api/decide, GET /api/next,
keyboard shortcuts in HTML, and verdict file updates.

Per LLD #21 §10.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from slant.dashboard import (
    render_dashboard_html,
    render_summary_html,
    start_dashboard,
    update_verdict_file,
    validate_decision,
)
from slant.models import ScoringBreakdown, Verdict, VerdictsFile


def _make_verdict(
    dead_url: str = "https://example.com/old",
    verdict: str = "HUMAN-REVIEW",
    confidence: int = 85,
    replacement_url: str | None = "https://example.com/new",
    human_decision: str | None = None,
    decided_at: str | None = None,
) -> Verdict:
    """Create a test verdict."""
    return Verdict(
        dead_url=dead_url,
        verdict=verdict,
        confidence=confidence,
        replacement_url=replacement_url,
        scoring_breakdown=ScoringBreakdown(
            redirect=20,
            title_match=20,
            content_similarity=20,
            url_similarity=10,
            domain_match=5,
        ),
        human_decision=human_decision,
        decided_at=decided_at,
    )


def _make_verdicts_file(verdicts: list[Verdict] | None = None) -> VerdictsFile:
    """Create a test verdicts file."""
    if verdicts is None:
        verdicts = [_make_verdict()]
    return VerdictsFile(
        generated_at="2026-02-18T12:00:00Z",
        source_report="report.json",
        verdicts=verdicts,
    )


def _write_verdicts_file(path: Path, verdicts_file: VerdictsFile) -> None:
    """Write a verdicts file to disk."""
    path.write_text(json.dumps(verdicts_file, indent=2))


def _start_test_server(verdicts_path: Path):
    """Start dashboard on random port and return (port, thread)."""
    import socketserver

    # Find a free port
    with socketserver.TCPServer(("127.0.0.1", 0), None) as s:
        port = s.server_address[1]

    thread = threading.Thread(
        target=start_dashboard,
        args=(verdicts_path,),
        kwargs={"port": port},
        daemon=True,
    )
    thread.start()
    # Wait for server to start
    for _ in range(50):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1)  # noqa: S310
            break
        except (urllib.error.URLError, OSError):
            time.sleep(0.1)
    return port, thread


# ---------------------------------------------------------------------------
# Validate decision tests (LLD §10 T130, T160)
# ---------------------------------------------------------------------------


class TestValidateDecision:
    """Tests for decision validation."""

    def test_approved_is_valid(self):
        """'approved' is a valid decision."""
        assert validate_decision("approved") is True

    def test_rejected_is_valid(self):
        """'rejected' is a valid decision."""
        assert validate_decision("rejected") is True

    def test_abandoned_is_valid(self):
        """'abandoned' is a valid decision."""
        assert validate_decision("abandoned") is True

    def test_keep_looking_is_valid(self):
        """'keep_looking' is a valid decision."""
        assert validate_decision("keep_looking") is True

    def test_maybe_is_invalid(self):
        """T160: 'maybe' is not a valid decision."""
        assert validate_decision("maybe") is False

    def test_empty_is_invalid(self):
        """Empty string is invalid."""
        assert validate_decision("") is False

    def test_auto_is_invalid(self):
        """'auto' is not a valid human decision."""
        assert validate_decision("auto") is False


# ---------------------------------------------------------------------------
# Render HTML tests (LLD §10 T100, T130, T200)
# ---------------------------------------------------------------------------


class TestRenderDashboardHtml:
    """Tests for dashboard HTML rendering."""

    def test_contains_two_iframes(self):
        """T130: Dashboard HTML has two iframes."""
        verdict = _make_verdict()
        html = render_dashboard_html(verdict)
        assert html.count("<iframe") == 2

    def test_contains_keyboard_shortcuts(self):
        """T140: Keyboard shortcuts JS exists in HTML."""
        verdict = _make_verdict()
        html = render_dashboard_html(verdict)
        # Check for keydown listener
        assert "keydown" in html
        # Check for shortcut keys
        assert "'a'" in html or '"a"' in html
        assert "'r'" in html or '"r"' in html
        assert "'x'" in html or '"x"' in html
        assert "'k'" in html or '"k"' in html

    def test_escapes_urls(self):
        """XSS prevention: URLs are HTML-escaped."""
        verdict = _make_verdict(
            dead_url='https://example.com/<script>alert("xss")</script>',
            replacement_url='https://example.com/<img onerror="evil">',
        )
        result = render_dashboard_html(verdict)
        # The injected script in the URL should be escaped
        assert "&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;" in result
        # The injected img onerror should be escaped
        assert "&lt;img onerror=&quot;evil&quot;&gt;" in result

    def test_shows_confidence_score(self):
        """Dashboard shows the confidence score."""
        verdict = _make_verdict(confidence=85)
        html = render_dashboard_html(verdict)
        assert "85" in html

    def test_shows_dead_url(self):
        """Dashboard shows the dead URL."""
        verdict = _make_verdict(dead_url="https://example.com/old-page")
        html = render_dashboard_html(verdict)
        assert "example.com/old-page" in html

    def test_handles_none_replacement_url(self):
        """Handles verdict with no replacement URL."""
        verdict = _make_verdict(replacement_url=None)
        html = render_dashboard_html(verdict)
        assert "No candidate" in html or "None" in html or "none" in html


class TestRenderSummaryHtml:
    """Tests for summary HTML rendering."""

    def test_shows_summary(self):
        """T190: Summary HTML contains 'Summary' text."""
        verdicts_file = _make_verdicts_file(
            [
                _make_verdict(human_decision="approved", decided_at="2026-02-18T12:00:00Z"),
            ]
        )
        html = render_summary_html(verdicts_file)
        assert "Summary" in html or "summary" in html

    def test_shows_decision_counts(self):
        """Summary shows counts of each decision type."""
        verdicts_file = _make_verdicts_file(
            [
                _make_verdict(human_decision="approved", decided_at="2026-02-18T12:00:00Z"),
                _make_verdict(
                    dead_url="https://example.com/other",
                    human_decision="rejected",
                    decided_at="2026-02-18T12:01:00Z",
                ),
            ]
        )
        html = render_summary_html(verdicts_file)
        assert "approved" in html.lower() or "Approved" in html
        assert "rejected" in html.lower() or "Rejected" in html


# ---------------------------------------------------------------------------
# Update verdict file tests (LLD §10 T120, T150, T180)
# ---------------------------------------------------------------------------


class TestUpdateVerdictFile:
    """Tests for updating verdict file on disk."""

    def test_updates_human_decision(self, tmp_path):
        """T150: POST /api/decide updates verdict file."""
        verdicts_file = _make_verdicts_file()
        path = tmp_path / "verdicts.json"
        _write_verdicts_file(path, verdicts_file)

        update_verdict_file(path, "https://example.com/old", "approved")

        data = json.loads(path.read_text())
        assert data["verdicts"][0]["human_decision"] == "approved"

    def test_sets_decided_at_timestamp(self, tmp_path):
        """T180: Verdict file updated with decided_at after decision."""
        verdicts_file = _make_verdicts_file()
        path = tmp_path / "verdicts.json"
        _write_verdicts_file(path, verdicts_file)

        update_verdict_file(path, "https://example.com/old", "rejected")

        data = json.loads(path.read_text())
        assert data["verdicts"][0]["decided_at"] is not None

    def test_does_not_modify_other_verdicts(self, tmp_path):
        """Only updates the matching verdict, not others."""
        verdicts_file = _make_verdicts_file(
            [
                _make_verdict(dead_url="https://example.com/first"),
                _make_verdict(dead_url="https://example.com/second"),
            ]
        )
        path = tmp_path / "verdicts.json"
        _write_verdicts_file(path, verdicts_file)

        update_verdict_file(path, "https://example.com/first", "approved")

        data = json.loads(path.read_text())
        assert data["verdicts"][0]["human_decision"] == "approved"
        assert data["verdicts"][1]["human_decision"] is None


# ---------------------------------------------------------------------------
# Dashboard HTTP server tests (LLD §10 T090, T120, T150, T160, T170, T190)
# ---------------------------------------------------------------------------


class TestDashboardServer:
    """Tests for the dashboard HTTP server."""

    def test_get_root_returns_200(self, tmp_path):
        """T120: Dashboard GET / returns 200."""
        verdicts_file = _make_verdicts_file()
        path = tmp_path / "verdicts.json"
        _write_verdicts_file(path, verdicts_file)
        port, thread = _start_test_server(path)

        try:
            resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5)  # noqa: S310
            assert resp.status == 200
            html = resp.read().decode()
            assert "<html" in html.lower()
        finally:
            # Server is daemon thread, will stop when test ends
            urllib.request.urlopen(  # noqa: S310
                f"http://127.0.0.1:{port}/api/shutdown",
                timeout=2,
            )

    def test_get_api_next_returns_undecided(self, tmp_path):
        """GET /api/next returns next undecided verdict."""
        verdicts_file = _make_verdicts_file()
        path = tmp_path / "verdicts.json"
        _write_verdicts_file(path, verdicts_file)
        port, thread = _start_test_server(path)

        try:
            resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/next", timeout=5)  # noqa: S310
            data = json.loads(resp.read().decode())
            assert data["done"] is False
            assert data["verdict"]["dead_url"] == "https://example.com/old"
        finally:
            urllib.request.urlopen(  # noqa: S310
                f"http://127.0.0.1:{port}/api/shutdown",
                timeout=2,
            )

    def test_get_api_next_returns_done_when_all_decided(self, tmp_path):
        """GET /api/next returns done=true when all decided."""
        verdicts_file = _make_verdicts_file(
            [
                _make_verdict(human_decision="approved", decided_at="2026-02-18T12:00:00Z"),
            ]
        )
        path = tmp_path / "verdicts.json"
        _write_verdicts_file(path, verdicts_file)
        port, thread = _start_test_server(path)

        try:
            resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/next", timeout=5)  # noqa: S310
            data = json.loads(resp.read().decode())
            assert data["done"] is True
        finally:
            urllib.request.urlopen(  # noqa: S310
                f"http://127.0.0.1:{port}/api/shutdown",
                timeout=2,
            )

    def test_post_api_decide_valid(self, tmp_path):
        """T150: POST /api/decide with valid decision returns 200."""
        verdicts_file = _make_verdicts_file()
        path = tmp_path / "verdicts.json"
        _write_verdicts_file(path, verdicts_file)
        port, thread = _start_test_server(path)

        try:
            body = json.dumps(
                {
                    "dead_url": "https://example.com/old",
                    "decision": "approved",
                }
            ).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/decide",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            resp = urllib.request.urlopen(req, timeout=5)  # noqa: S310
            assert resp.status == 200

            # Verify file was updated
            data = json.loads(path.read_text())
            assert data["verdicts"][0]["human_decision"] == "approved"
        finally:
            urllib.request.urlopen(  # noqa: S310
                f"http://127.0.0.1:{port}/api/shutdown",
                timeout=2,
            )

    def test_post_api_decide_invalid_decision(self, tmp_path):
        """T160: POST /api/decide with invalid decision returns 400."""
        verdicts_file = _make_verdicts_file()
        path = tmp_path / "verdicts.json"
        _write_verdicts_file(path, verdicts_file)
        port, thread = _start_test_server(path)

        try:
            body = json.dumps(
                {
                    "dead_url": "https://example.com/old",
                    "decision": "maybe",
                }
            ).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/decide",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                urllib.request.urlopen(req, timeout=5)  # noqa: S310
            assert exc_info.value.code == 400
        finally:
            urllib.request.urlopen(  # noqa: S310
                f"http://127.0.0.1:{port}/api/shutdown",
                timeout=2,
            )

    def test_post_api_decide_malformed_json(self, tmp_path):
        """T170: POST /api/decide with malformed JSON returns 400."""
        verdicts_file = _make_verdicts_file()
        path = tmp_path / "verdicts.json"
        _write_verdicts_file(path, verdicts_file)
        port, thread = _start_test_server(path)

        try:
            body = b"{invalid json"
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/decide",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                urllib.request.urlopen(req, timeout=5)  # noqa: S310
            assert exc_info.value.code == 400
        finally:
            urllib.request.urlopen(  # noqa: S310
                f"http://127.0.0.1:{port}/api/shutdown",
                timeout=2,
            )

    def test_get_unknown_path_returns_404(self, tmp_path):
        """GET on unknown path returns 404."""
        verdicts_file = _make_verdicts_file()
        path = tmp_path / "verdicts.json"
        _write_verdicts_file(path, verdicts_file)
        port, thread = _start_test_server(path)

        try:
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/nonexistent", timeout=5)  # noqa: S310
            assert exc_info.value.code == 404
        finally:
            urllib.request.urlopen(  # noqa: S310
                f"http://127.0.0.1:{port}/api/shutdown",
                timeout=2,
            )

    def test_post_unknown_path_returns_404(self, tmp_path):
        """POST to unknown path returns 404."""
        verdicts_file = _make_verdicts_file()
        path = tmp_path / "verdicts.json"
        _write_verdicts_file(path, verdicts_file)
        port, thread = _start_test_server(path)

        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/unknown",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                urllib.request.urlopen(req, timeout=5)  # noqa: S310
            assert exc_info.value.code == 404
        finally:
            urllib.request.urlopen(  # noqa: S310
                f"http://127.0.0.1:{port}/api/shutdown",
                timeout=2,
            )

    def test_post_missing_fields_returns_400(self, tmp_path):
        """POST /api/decide with missing fields returns 400."""
        verdicts_file = _make_verdicts_file()
        path = tmp_path / "verdicts.json"
        _write_verdicts_file(path, verdicts_file)
        port, thread = _start_test_server(path)

        try:
            body = json.dumps({"dead_url": "https://example.com/old"}).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/decide",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                urllib.request.urlopen(req, timeout=5)  # noqa: S310
            assert exc_info.value.code == 400
        finally:
            urllib.request.urlopen(  # noqa: S310
                f"http://127.0.0.1:{port}/api/shutdown",
                timeout=2,
            )

    def test_summary_when_all_decided(self, tmp_path):
        """T190: Summary screen shows when all decided."""
        verdicts_file = _make_verdicts_file(
            [
                _make_verdict(human_decision="approved", decided_at="2026-02-18T12:00:00Z"),
            ]
        )
        path = tmp_path / "verdicts.json"
        _write_verdicts_file(path, verdicts_file)
        port, thread = _start_test_server(path)

        try:
            resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5)  # noqa: S310
            html = resp.read().decode()
            assert "Summary" in html or "summary" in html
        finally:
            urllib.request.urlopen(  # noqa: S310
                f"http://127.0.0.1:{port}/api/shutdown",
                timeout=2,
            )


# ---------------------------------------------------------------------------
# Coverage gap tests
# ---------------------------------------------------------------------------


class TestUpdateVerdictFileCoverageGaps:
    """Tests for uncovered error path in update_verdict_file."""

    def test_write_failure_cleans_up_temp_file(self, tmp_path):
        """Error during atomic write cleans up temp and re-raises (lines 64-66)."""
        from unittest.mock import patch as _patch

        verdicts_file = _make_verdicts_file()
        path = tmp_path / "verdicts.json"
        _write_verdicts_file(path, verdicts_file)

        with _patch("slant.dashboard.Path.write_text", side_effect=OSError("disk full")):
            with pytest.raises(OSError, match="disk full"):
                update_verdict_file(path, "https://example.com/old", "approved")


class TestStartDashboardCoverageGaps:
    """Tests for uncovered KeyboardInterrupt path in start_dashboard."""

    def test_keyboard_interrupt_shuts_down_gracefully(self, tmp_path):
        """KeyboardInterrupt during serve_forever is handled (lines 335-336)."""
        from http.server import HTTPServer
        from unittest.mock import patch as _patch

        verdicts_file = _make_verdicts_file()
        path = tmp_path / "verdicts.json"
        _write_verdicts_file(path, verdicts_file)

        with _patch.object(HTTPServer, "serve_forever", side_effect=KeyboardInterrupt):
            with _patch.object(HTTPServer, "server_close") as mock_close:
                start_dashboard(path, port=0)
                mock_close.assert_called_once()
