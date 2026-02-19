"""Tests for pipeline cost tracker.

See LLD #22 §10.0 T170/T180/T270: Cost accumulation, limit halt, display format.
"""

from __future__ import annotations

from gh_link_auditor.pipeline.cost_tracker import CostTracker, count_tokens


class TestCostTracker:
    """Tests for CostTracker class."""

    def test_initial_total_is_zero(self) -> None:
        ct = CostTracker(max_cost_usd=5.00)
        assert ct.get_total() == 0.0

    def test_default_model(self) -> None:
        ct = CostTracker(max_cost_usd=5.00)
        assert ct.model == "gpt-4o-mini"

    def test_custom_model(self) -> None:
        ct = CostTracker(max_cost_usd=5.00, model="gpt-4o")
        assert ct.model == "gpt-4o"

    def test_estimate_cost_gpt4o_mini(self) -> None:
        ct = CostTracker(max_cost_usd=5.00, model="gpt-4o-mini")
        # gpt-4o-mini: $0.15/1M input, $0.60/1M output
        cost = ct.estimate_cost(1_000_000, 1_000_000)
        assert cost > 0
        assert abs(cost - 0.75) < 0.01  # $0.15 + $0.60

    def test_estimate_cost_zero_tokens(self) -> None:
        ct = CostTracker(max_cost_usd=5.00)
        cost = ct.estimate_cost(0, 0)
        assert cost == 0.0

    def test_record_call_returns_cost_record(self) -> None:
        ct = CostTracker(max_cost_usd=5.00)
        record = ct.record_call("n3", 100, 50)
        assert record["node"] == "n3"
        assert record["model"] == "gpt-4o-mini"
        assert record["input_tokens"] == 100
        assert record["output_tokens"] == 50
        assert record["estimated_cost_usd"] > 0
        assert "timestamp" in record

    def test_record_call_accumulates_total(self) -> None:
        ct = CostTracker(max_cost_usd=5.00)
        ct.record_call("n3", 1000, 500)
        first = ct.get_total()
        ct.record_call("n3", 1000, 500)
        second = ct.get_total()
        assert second > first
        assert abs(second - 2 * first) < 0.0001

    def test_three_calls_accumulate(self) -> None:
        ct = CostTracker(max_cost_usd=5.00)
        r1 = ct.record_call("n2", 100, 50)
        r2 = ct.record_call("n3", 200, 100)
        r3 = ct.record_call("n3", 300, 150)
        expected = r1["estimated_cost_usd"] + r2["estimated_cost_usd"] + r3["estimated_cost_usd"]
        assert abs(ct.get_total() - expected) < 0.0001

    def test_check_limit_false_when_under(self) -> None:
        ct = CostTracker(max_cost_usd=5.00)
        ct.record_call("n3", 100, 50)
        assert ct.check_limit() is False

    def test_check_limit_true_when_over(self) -> None:
        ct = CostTracker(max_cost_usd=0.001)
        ct.record_call("n3", 100_000, 100_000)
        assert ct.check_limit() is True

    def test_check_limit_true_at_exact_limit(self) -> None:
        ct = CostTracker(max_cost_usd=0.0)
        # Any call should trigger
        ct.record_call("n3", 100, 50)
        assert ct.check_limit() is True

    def test_format_status(self) -> None:
        ct = CostTracker(max_cost_usd=5.00)
        status = ct.format_status()
        assert "$0.00" in status
        assert "$5.00" in status
        assert "limit" in status.lower()

    def test_format_status_after_calls(self) -> None:
        ct = CostTracker(max_cost_usd=10.00)
        ct.record_call("n3", 1_000_000, 500_000)
        status = ct.format_status()
        assert "$10.00" in status
        # Should show non-zero cost
        assert "$0.00" not in status or ct.get_total() == 0

    def test_get_records(self) -> None:
        ct = CostTracker(max_cost_usd=5.00)
        ct.record_call("n2", 100, 50)
        ct.record_call("n3", 200, 100)
        records = ct.get_records()
        assert len(records) == 2
        assert records[0]["node"] == "n2"
        assert records[1]["node"] == "n3"


class TestCountTokens:
    """Tests for count_tokens()."""

    def test_empty_string(self) -> None:
        count = count_tokens("")
        assert count == 0

    def test_short_text(self) -> None:
        count = count_tokens("Hello, world!")
        assert count > 0
        assert count < 10

    def test_longer_text(self) -> None:
        count = count_tokens("This is a longer piece of text that should have more tokens.")
        assert count > 5

    def test_consistent_results(self) -> None:
        text = "Consistency test string"
        c1 = count_tokens(text)
        c2 = count_tokens(text)
        assert c1 == c2

    def test_unknown_model_fallback(self) -> None:
        """Unknown model should still return a count via fallback."""
        count = count_tokens("Hello world", model="unknown-model")
        assert count > 0
