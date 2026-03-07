"""HITL dashboard for Slant verdict review.

Local HTTP server for reviewing and deciding on uncertain verdicts.
Bound to 127.0.0.1 only (localhost). Inline HTML/CSS/JS.

See LLD #21 §2.5 "Dashboard Flow" for specification.
"""

from __future__ import annotations

import html
import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from slant.models import Verdict, VerdictsFile

_ALLOWED_DECISIONS = {"approved", "rejected", "abandoned", "keep_looking"}


def validate_decision(decision: str) -> bool:
    """Validate decision value against allowed set.

    Args:
        decision: Decision string to validate.

    Returns:
        True if valid, False otherwise.
    """
    return decision in _ALLOWED_DECISIONS


def update_verdict_file(verdicts_path: Path, dead_url: str, decision: str) -> None:
    """Update verdict in file with human decision and timestamp.

    Uses atomic write via temp file + rename.

    Args:
        verdicts_path: Path to verdicts JSON file.
        dead_url: Dead URL to update.
        decision: Human decision value.
    """
    import os
    import tempfile

    data = json.loads(verdicts_path.read_text())
    for v in data["verdicts"]:
        if v["dead_url"] == dead_url:
            v["human_decision"] = decision
            v["decided_at"] = datetime.now(timezone.utc).isoformat()
            break

    fd, tmp_path_str = tempfile.mkstemp(
        dir=str(verdicts_path.parent),
        suffix=".tmp",
    )
    tmp_path = Path(tmp_path_str)
    try:
        os.close(fd)
        tmp_path.write_text(json.dumps(data, indent=2))
        tmp_path.replace(verdicts_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def render_dashboard_html(verdict: Verdict) -> str:
    """Generate dashboard HTML for a single review item.

    Displays side-by-side iframes with archived and candidate URLs.
    Includes keyboard shortcuts via JavaScript.

    Args:
        verdict: Verdict to render for review.

    Returns:
        HTML string.
    """
    dead_url = html.escape(verdict["dead_url"])
    replacement_url = verdict.get("replacement_url")
    confidence = verdict["confidence"]
    tier = html.escape(verdict["verdict"])
    breakdown = verdict["scoring_breakdown"]

    if replacement_url:
        candidate_escaped = html.escape(replacement_url)
        candidate_iframe = f'<iframe src="{candidate_escaped}" sandbox="allow-same-origin"></iframe>'
        candidate_link = f'<a href="{candidate_escaped}" target="_blank">{candidate_escaped}</a>'
    else:
        candidate_iframe = '<div class="fallback">No candidate URL available</div>'
        candidate_link = "None"

    return f"""<!DOCTYPE html>
<html>
<head>
<title>Slant — Review Verdict</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 0; padding: 0; background: #f5f5f5; }}
.header {{ background: #333; color: white; padding: 16px 24px; }}
.header h1 {{ margin: 0; font-size: 20px; }}
.meta {{ background: #fff; padding: 16px 24px; border-bottom: 1px solid #ddd; }}
.meta .url {{ font-family: monospace; word-break: break-all; }}
.meta .score {{ font-size: 24px; font-weight: bold; }}
.iframes {{ display: flex; height: 60vh; gap: 8px; padding: 8px; }}
.iframes > div {{ flex: 1; display: flex; flex-direction: column; }}
.iframes label {{ font-weight: bold; padding: 4px 8px; background: #eee; }}
.iframes iframe {{ flex: 1; border: 1px solid #ccc; }}
.iframes .fallback {{ flex: 1; border: 1px solid #ccc; display: flex; align-items: center;
    justify-content: center; color: #666; background: #fafafa; }}
.actions {{ padding: 16px 24px; text-align: center; }}
.actions button {{ padding: 12px 24px; margin: 0 8px; font-size: 16px; cursor: pointer;
    border: none; border-radius: 4px; color: white; }}
.btn-approve {{ background: #28a745; }}
.btn-reject {{ background: #dc3545; }}
.btn-abandon {{ background: #6c757d; }}
.btn-keep {{ background: #007bff; }}
.shortcuts {{ color: #666; font-size: 13px; margin-top: 8px; }}
.breakdown {{ font-size: 13px; color: #555; }}
.breakdown span {{ margin-right: 12px; }}
</style>
</head>
<body>
<div class="header"><h1>Slant — Verdict Review</h1></div>
<div class="meta">
  <p><strong>Dead URL:</strong> <span class="url">{dead_url}</span></p>
  <p><strong>Candidate:</strong> <span class="url">{candidate_link}</span></p>
  <p><strong>Confidence:</strong> <span class="score">{confidence}</span> ({tier})</p>
  <div class="breakdown">
    <span>Redirect: {breakdown["redirect"]:.1f}</span>
    <span>Title: {breakdown["title_match"]:.1f}</span>
    <span>Content: {breakdown["content_similarity"]:.1f}</span>
    <span>URL Path: {breakdown["url_similarity"]:.1f}</span>
    <span>Domain: {breakdown["domain_match"]:.1f}</span>
  </div>
</div>
<div class="iframes">
  <div><label>Archived</label>
    <iframe src="https://web.archive.org/web/{dead_url}" sandbox="allow-same-origin"></iframe>
  </div>
  <div><label>Candidate</label>
    {candidate_iframe}
  </div>
</div>
<div class="actions">
  <button class="btn-approve" onclick="decide('approved')">Approve (a)</button>
  <button class="btn-reject" onclick="decide('rejected')">Reject (r)</button>
  <button class="btn-abandon" onclick="decide('abandoned')">Abandon (x)</button>
  <button class="btn-keep" onclick="decide('keep_looking')">Keep Looking (k)</button>
  <p class="shortcuts">Keyboard: a=approve, r=reject, x=abandon, k=keep_looking</p>
</div>
<script>
function decide(decision) {{
  fetch('/api/decide', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{dead_url: '{dead_url}', decision: decision}})
  }}).then(r => {{
    if (r.ok) window.location.reload();
    else alert('Error: ' + r.status);
  }});
}}
document.addEventListener('keydown', function(e) {{
  if (e.key === 'a') decide('approved');
  if (e.key === 'r') decide('rejected');
  if (e.key === 'x') decide('abandoned');
  if (e.key === 'k') decide('keep_looking');
}});
</script>
</body>
</html>"""


def render_summary_html(verdicts_file: VerdictsFile) -> str:
    """Generate summary HTML when all items have been decided.

    Shows counts by decision type and a table of all verdicts.

    Args:
        verdicts_file: Complete verdicts file.

    Returns:
        HTML string.
    """
    counts: dict[str, int] = {}
    for v in verdicts_file["verdicts"]:
        d = v.get("human_decision") or "pending"
        counts[d] = counts.get(d, 0) + 1

    counts_html = "".join(f"<li><strong>{html.escape(k)}:</strong> {v}</li>" for k, v in sorted(counts.items()))

    rows_html = ""
    for v in verdicts_file["verdicts"]:
        rows_html += (
            f"<tr><td>{html.escape(v['dead_url'])}</td>"
            f"<td>{html.escape(v.get('replacement_url') or 'N/A')}</td>"
            f"<td>{v['confidence']}</td>"
            f"<td>{html.escape(v['verdict'])}</td>"
            f"<td>{html.escape(v.get('human_decision') or 'pending')}</td></tr>"
        )

    return f"""<!DOCTYPE html>
<html>
<head>
<title>Slant — Summary</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 0; padding: 24px; background: #f5f5f5; }}
h1 {{ color: #333; }}
table {{ border-collapse: collapse; width: 100%; background: white; }}
th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; }}
th {{ background: #333; color: white; }}
ul {{ list-style: none; padding: 0; }}
li {{ padding: 4px 0; }}
</style>
</head>
<body>
<h1>Summary — All Verdicts Decided</h1>
<h2>Decision Counts</h2>
<ul>{counts_html}</ul>
<h2>All Verdicts</h2>
<table>
<tr><th>Dead URL</th><th>Replacement</th><th>Confidence</th><th>Tier</th><th>Decision</th></tr>
{rows_html}
</table>
</body>
</html>"""


class SlantRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for Slant dashboard."""

    verdicts_path: Path

    def log_message(self, format, *args):
        """Suppress default logging."""

    def _load_verdicts(self) -> VerdictsFile:
        """Load verdicts from disk."""
        return json.loads(self.verdicts_path.read_text())

    def _find_undecided(self, data: VerdictsFile) -> Verdict | None:
        """Find first undecided verdict."""
        for v in data["verdicts"]:
            if v["human_decision"] is None:
                return v
        return None

    def _send_json(self, status: int, data: dict) -> None:
        """Send JSON response."""
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status: int, html_content: str) -> None:
        """Send HTML response."""
        body = html_content.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        """Handle GET requests (/, /api/next, /api/shutdown)."""
        if self.path == "/":
            data = self._load_verdicts()
            undecided = self._find_undecided(data)
            if undecided:
                self._send_html(200, render_dashboard_html(undecided))
            else:
                self._send_html(200, render_summary_html(data))

        elif self.path == "/api/next":
            data = self._load_verdicts()
            undecided = self._find_undecided(data)
            if undecided:
                self._send_json(200, {"done": False, "verdict": undecided})
            else:
                self._send_json(200, {"done": True})

        elif self.path == "/api/shutdown":
            self._send_json(200, {"status": "shutting_down"})
            threading.Thread(target=self.server.shutdown, daemon=True).start()

        else:
            self.send_error(404)

    def do_POST(self) -> None:
        """Handle POST requests (/api/decide)."""
        if self.path != "/api/decide":
            self.send_error(404)
            return

        content_length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_length)

        try:
            body = json.loads(raw_body)
        except (json.JSONDecodeError, ValueError):
            self._send_json(400, {"error": "Malformed JSON"})
            return

        dead_url = body.get("dead_url")
        decision = body.get("decision")

        if not dead_url or not decision:
            self._send_json(400, {"error": "Missing dead_url or decision"})
            return

        if not validate_decision(decision):
            self._send_json(400, {"error": f"Invalid decision: {decision}"})
            return

        update_verdict_file(self.verdicts_path, dead_url, decision)
        self._send_json(200, {"status": "ok"})


def start_dashboard(verdicts_path: Path, port: int = 8913) -> None:
    """Start HITL dashboard HTTP server.

    Binds to 127.0.0.1 only (localhost). Blocks until shutdown.

    Args:
        verdicts_path: Path to verdicts JSON file.
        port: Port to bind to (default: 8913).
    """
    SlantRequestHandler.verdicts_path = verdicts_path
    server = HTTPServer(("127.0.0.1", port), SlantRequestHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
