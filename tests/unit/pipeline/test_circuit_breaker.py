"""Tests for pipeline circuit breaker.

See LLD #22 §10.0 T080/T090: Circuit breaker triggers/passes.
"""

from __future__ import annotations

from gh_link_auditor.pipeline.circuit_breaker import CircuitBreaker
from gh_link_auditor.pipeline.state import DeadLink


def _make_dead_links(count: int) -> list[DeadLink]:
    """Create a list of N dead links for testing."""
    return [
        DeadLink(
            url=f"https://example.com/dead-{i}",
            source_file="README.md",
            line_number=i,
            link_text=f"link {i}",
            http_status=404,
            error_type="http_error",
        )
        for i in range(count)
    ]


class TestCircuitBreaker:
    """Tests for CircuitBreaker class."""

    def test_default_threshold_is_50(self) -> None:
        cb = CircuitBreaker()
        assert cb.max_links == 50

    def test_custom_threshold(self) -> None:
        cb = CircuitBreaker(max_links=100)
        assert cb.max_links == 100

    def test_triggers_when_count_exceeds_threshold(self) -> None:
        cb = CircuitBreaker(max_links=50)
        dead_links = _make_dead_links(51)
        triggered, message = cb.check_link_count(dead_links)
        assert triggered is True

    def test_passes_at_exact_threshold(self) -> None:
        cb = CircuitBreaker(max_links=50)
        dead_links = _make_dead_links(50)
        triggered, message = cb.check_link_count(dead_links)
        assert triggered is False

    def test_passes_under_threshold(self) -> None:
        cb = CircuitBreaker(max_links=50)
        dead_links = _make_dead_links(10)
        triggered, message = cb.check_link_count(dead_links)
        assert triggered is False

    def test_passes_with_empty_list(self) -> None:
        cb = CircuitBreaker(max_links=50)
        triggered, message = cb.check_link_count([])
        assert triggered is False

    def test_trigger_message_contains_count(self) -> None:
        cb = CircuitBreaker(max_links=50)
        dead_links = _make_dead_links(75)
        triggered, message = cb.check_link_count(dead_links)
        assert "75" in message

    def test_trigger_message_contains_threshold(self) -> None:
        cb = CircuitBreaker(max_links=50)
        dead_links = _make_dead_links(51)
        _, message = cb.check_link_count(dead_links)
        assert "50" in message

    def test_pass_message_empty_or_ok(self) -> None:
        cb = CircuitBreaker(max_links=50)
        dead_links = _make_dead_links(30)
        triggered, message = cb.check_link_count(dead_links)
        assert triggered is False
        # Message should be empty or informational, not an error
        assert "triggered" not in message.lower() or message == ""

    def test_threshold_of_zero_always_triggers(self) -> None:
        cb = CircuitBreaker(max_links=0)
        dead_links = _make_dead_links(1)
        triggered, _ = cb.check_link_count(dead_links)
        assert triggered is True

    def test_threshold_of_zero_with_empty_passes(self) -> None:
        cb = CircuitBreaker(max_links=0)
        triggered, _ = cb.check_link_count([])
        assert triggered is False

    def test_just_above_threshold(self) -> None:
        """Edge case: exactly threshold + 1."""
        cb = CircuitBreaker(max_links=10)
        dead_links = _make_dead_links(11)
        triggered, _ = cb.check_link_count(dead_links)
        assert triggered is True
