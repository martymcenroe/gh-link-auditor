"""Campaign metrics collection and reporting."""

from gh_link_auditor.metrics.collector import MetricsCollector
from gh_link_auditor.metrics.models import CampaignMetrics, PROutcome, RunReport
from gh_link_auditor.metrics.reporter import (
    format_campaign_text,
    format_report_json,
    format_report_text,
    generate_campaign_metrics,
    generate_run_report,
)

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
