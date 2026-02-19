"""Unit tests for HITL interactive console (LLD #10, §10.0).

TDD: Tests written BEFORE implementation.
All interactive input is mocked via ``builtins.input``.
"""

import json
from unittest.mock import patch

from hitl_console import (
    apply_resolution,
    filter_broken_links,
    run_hitl_console,
    save_results,
    validate_url,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sample_results():
    """Build a sample results list with mixed statuses."""
    return [
        {"url": "https://good.com", "status": "ok", "status_code": 200, "error": None},
        {"url": "https://broken.com", "status": "error", "status_code": 404, "error": "HTTP 404"},
        {"url": "https://also-good.com", "status": "ok", "status_code": 200, "error": None},
        {"url": "https://timeout.com", "status": "timeout", "status_code": None, "error": "Request timed out"},
        {"url": "https://dead.com", "status": "error", "status_code": 403, "error": "HTTP 403"},
    ]


def _all_ok_results():
    """Build a results list where everything is OK."""
    return [
        {"url": "https://good.com", "status": "ok", "status_code": 200, "error": None},
        {"url": "https://fine.com", "status": "ok", "status_code": 301, "error": None},
    ]


# ---------------------------------------------------------------------------
# T020: Filter broken links only (REQ-2)
# ---------------------------------------------------------------------------


class TestFilterBrokenLinks:
    def test_filter_broken_links_extracts_errors(self):
        results = _sample_results()
        broken = filter_broken_links(results)
        assert len(broken) == 3
        assert all(r["status"] != "ok" for r in broken)

    # T120: Filter with all OK
    def test_filter_all_ok_returns_empty(self):
        results = _all_ok_results()
        broken = filter_broken_links(results)
        assert broken == []


# ---------------------------------------------------------------------------
# T100, T110: URL validation
# ---------------------------------------------------------------------------


class TestValidateUrl:
    # T100
    def test_validate_url_accepts_https(self):
        assert validate_url("https://example.com") is True

    def test_validate_url_accepts_http(self):
        assert validate_url("http://example.com/path") is True

    # T110
    def test_validate_url_rejects_invalid(self):
        assert validate_url("not-a-url") is False

    def test_validate_url_rejects_empty(self):
        assert validate_url("") is False

    def test_validate_url_rejects_ftp(self):
        assert validate_url("ftp://files.example.com") is False


# ---------------------------------------------------------------------------
# T040, T050: Apply resolution actions (REQ-4, REQ-5)
# ---------------------------------------------------------------------------


class TestApplyResolution:
    # T040
    def test_apply_resolution_replace(self):
        link = {"url": "https://broken.com", "status": "error"}
        apply_resolution(link, "replace", "https://fixed.com", None)
        assert link["resolution"]["action"] == "replace"
        assert link["resolution"]["new_url"] == "https://fixed.com"

    def test_apply_resolution_remove(self):
        link = {"url": "https://broken.com", "status": "error"}
        apply_resolution(link, "remove", None, None)
        assert link["resolution"]["action"] == "remove"
        assert link["resolution"]["new_url"] is None

    def test_apply_resolution_ignore(self):
        link = {"url": "https://broken.com", "status": "error"}
        apply_resolution(link, "ignore", None, "false positive")
        assert link["resolution"]["action"] == "ignore"
        assert link["resolution"]["note"] == "false positive"

    def test_apply_resolution_keep(self):
        link = {"url": "https://broken.com", "status": "error"}
        apply_resolution(link, "keep", None, None)
        assert link["resolution"]["action"] == "keep"

    # T050: Resolution matches JSON schema
    def test_resolution_data_matches_schema(self):
        link = {"url": "https://broken.com", "status": "error"}
        apply_resolution(link, "replace", "https://fixed.com", "updated link")
        res = link["resolution"]
        assert "action" in res
        assert "new_url" in res
        assert "resolved_by" in res
        assert "resolved_at" in res
        assert "note" in res
        assert res["resolved_by"] == "human"
        # resolved_at should be an ISO 8601 timestamp
        assert "T" in res["resolved_at"]


# ---------------------------------------------------------------------------
# T060: Save progress writes JSON (REQ-6)
# ---------------------------------------------------------------------------


class TestSaveResults:
    def test_save_progress_writes_json(self, tmp_path):
        results = _sample_results()
        output = tmp_path / "report.json"
        save_results(results, str(output))
        assert output.exists()
        data = json.loads(output.read_text(encoding="utf-8"))
        assert len(data) == len(results)


# ---------------------------------------------------------------------------
# T030: Navigation forward/backward (REQ-3)
# ---------------------------------------------------------------------------


class TestNavigation:
    def test_navigation_forward_backward(self):
        """Simulates: next, next, prev, quit."""
        results = _sample_results()
        inputs = iter(["n", "n", "p", "q"])
        with patch("builtins.input", side_effect=inputs):
            updated = run_hitl_console(results)
        # Should return without error; results unchanged (no resolutions applied)
        assert updated is not None


# ---------------------------------------------------------------------------
# T130: Replace action flow
# ---------------------------------------------------------------------------


class TestReplaceFlow:
    def test_replace_action_sets_new_url(self):
        results = _sample_results()
        # Simulate: replace, enter URL, skip note, quit, confirm quit
        inputs = iter(["r", "https://new-url.com", "", "q", "n"])
        with patch("builtins.input", side_effect=inputs):
            updated = run_hitl_console(results)
        # Find the first broken link (index 1 in original results)
        broken = [r for r in updated if r.get("resolution")]
        assert len(broken) >= 1
        assert broken[0]["resolution"]["new_url"] == "https://new-url.com"


# ---------------------------------------------------------------------------
# T070: Quit with unsaved changes prompt (REQ-7)
# ---------------------------------------------------------------------------


class TestQuitBehaviour:
    def test_quit_with_unsaved_changes_prompts(self, capsys):
        results = _sample_results()
        # Apply a resolution, then quit — should prompt about unsaved changes
        # Simulate: ignore (makes a change), quit, confirm quit
        inputs = iter(["i", "q", "y"])
        with patch("builtins.input", side_effect=inputs):
            run_hitl_console(results)
        captured = capsys.readouterr()
        assert "unsaved" in captured.out.lower() or "save" in captured.out.lower()


# ---------------------------------------------------------------------------
# T080: EOF handling (REQ-8)
# ---------------------------------------------------------------------------


class TestSignalHandling:
    def test_eof_handling_graceful(self):
        results = _sample_results()
        with patch("builtins.input", side_effect=EOFError):
            updated = run_hitl_console(results)
        # Should return results without raising
        assert updated is not None

    # T090: Keyboard interrupt
    def test_keyboard_interrupt_handling(self):
        results = _sample_results()
        # Apply a resolution, then interrupt
        call_count = 0

        def _side_effect(prompt=""):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "i"  # apply ignore resolution
            raise KeyboardInterrupt

        with patch("builtins.input", side_effect=_side_effect):
            updated = run_hitl_console(results)
        # Should return with the resolution applied
        assert updated is not None


# ---------------------------------------------------------------------------
# T010: HITL mode invoked via --resolve flag (REQ-1)
# ---------------------------------------------------------------------------


class TestResolveFlag:
    def test_run_hitl_console_with_no_broken_links(self, capsys):
        results = _all_ok_results()
        updated = run_hitl_console(results)
        captured = capsys.readouterr()
        assert "no broken links" in captured.out.lower()
        assert updated == results
