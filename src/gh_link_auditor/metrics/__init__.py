"""Campaign metrics collection and reporting.

Note: reporter imports are lazy to avoid circular import with batch.engine.
The cycle is: metrics.__init__ → metrics.reporter → batch.models →
batch.__init__ → batch.engine → metrics.reporter (cycle).
"""

from gh_link_auditor.metrics.collector import MetricsCollector
from gh_link_auditor.metrics.models import CampaignMetrics, PROutcome, RunReport


def __getattr__(name: str):
    """Lazy import reporter functions to break circular import."""
    _reporter_names = {
        "format_campaign_text",
        "format_report_json",
        "format_report_text",
        "generate_campaign_metrics",
        "generate_run_report",
    }
    if name in _reporter_names:
        from gh_link_auditor.metrics import reporter

        return getattr(reporter, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "CampaignMetrics",
    "MetricsCollector",
    "PROutcome",
    "RunReport",
    "format_campaign_text",
    "format_report_json",
    "format_report_text",
    "generate_campaign_metrics",
    "generate_run_report",
]
