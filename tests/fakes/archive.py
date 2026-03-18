"""Fake ArchiveClient for testing.

Replaces MagicMock with a configurable fake that mirrors ArchiveClient's interface.
"""

from __future__ import annotations

from gh_link_auditor.archive_client import CDXResponse


class FakeArchiveClient:
    """Fake ArchiveClient with pre-configured responses."""

    def __init__(
        self,
        snapshot: CDXResponse | None = None,
        html: str | None = None,
        title: str | None = None,
        summary: str | None = None,
    ) -> None:
        self._snapshot = snapshot
        self._html = html
        self._title = title
        self._summary = summary

    def get_latest_snapshot(self, url: str) -> CDXResponse | None:
        """Return pre-configured snapshot."""
        return self._snapshot

    def fetch_snapshot_content(self, snapshot_url: str) -> str | None:
        """Return pre-configured HTML content."""
        return self._html

    def extract_title(self, html: str) -> str | None:
        """Return pre-configured title."""
        return self._title

    def extract_content_summary(self, html: str, max_chars: int = 500) -> str | None:
        """Return pre-configured summary."""
        return self._summary


def make_archive_hit(
    url: str = "https://example.com/docs",
    timestamp: str = "20240101120000",
    title: str = "Example Docs",
    summary: str = "Content here",
) -> FakeArchiveClient:
    """Create a FakeArchiveClient that returns a snapshot with title and summary."""
    snapshot = CDXResponse(
        url=url,
        timestamp=timestamp,
        original=url,
        mimetype="text/html",
        statuscode="200",
        digest="ABC",
        length="1234",
    )
    html = f"<html><head><title>{title}</title></head><body>{summary}</body></html>"
    return FakeArchiveClient(
        snapshot=snapshot,
        html=html,
        title=title,
        summary=summary,
    )


def make_archive_miss() -> FakeArchiveClient:
    """Create a FakeArchiveClient that returns no snapshot."""
    return FakeArchiveClient()
