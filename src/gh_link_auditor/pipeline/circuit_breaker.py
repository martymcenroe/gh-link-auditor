"""Circuit breaker for pipeline volume controls.

Halts pipeline when dead link count exceeds configurable threshold
to prevent runaway LLM costs.

See LLD #22 §2.4 for CircuitBreaker specification.
"""

from __future__ import annotations

from gh_link_auditor.pipeline.state import DeadLink


class CircuitBreaker:
    """Circuit breaker for pipeline cost and volume controls."""

    def __init__(self, max_links: int = 50) -> None:
        """Initialize circuit breaker with link threshold.

        Args:
            max_links: Maximum number of dead links before triggering.
        """
        self.max_links = max_links

    def check_link_count(self, dead_links: list[DeadLink]) -> tuple[bool, str]:
        """Check if dead link count exceeds threshold.

        Args:
            dead_links: List of dead links found during scan.

        Returns:
            Tuple of (triggered, message). triggered is True if count
            exceeds max_links threshold.
        """
        count = len(dead_links)
        if count > self.max_links:
            return (
                True,
                f"Circuit breaker triggered: {count} dead links exceed threshold of {self.max_links}",
            )
        return (False, "")
