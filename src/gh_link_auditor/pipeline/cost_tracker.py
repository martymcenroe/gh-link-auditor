"""LLM cost accumulator and circuit breaker.

Tracks token usage and estimated costs across pipeline nodes,
enforcing a configurable cost limit.

See LLD #22 §2.4 for CostTracker specification.
"""

from __future__ import annotations

from datetime import datetime, timezone

import tiktoken

from gh_link_auditor.pipeline.state import CostRecord

# Pricing per 1M tokens (USD)
_MODEL_PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "claude-3-haiku": (0.25, 1.25),
    "claude-3-sonnet": (3.00, 15.00),
}

# Default pricing for unknown models
_DEFAULT_PRICING = (0.50, 2.00)


class CostTracker:
    """Track LLM costs and enforce cost limits."""

    def __init__(self, max_cost_usd: float, model: str = "gpt-4o-mini") -> None:
        """Initialize cost tracker with limit and model.

        Args:
            max_cost_usd: Maximum allowed cost in USD.
            model: LLM model name for pricing lookup.
        """
        self.max_cost_usd = max_cost_usd
        self.model = model
        self._total_cost: float = 0.0
        self._records: list[CostRecord] = []

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost for given token counts.

        Args:
            input_tokens: Number of input/prompt tokens.
            output_tokens: Number of output/completion tokens.

        Returns:
            Estimated cost in USD.
        """
        input_price, output_price = _MODEL_PRICING.get(self.model, _DEFAULT_PRICING)
        return (input_tokens * input_price + output_tokens * output_price) / 1_000_000

    def record_call(
        self,
        node: str,
        input_tokens: int,
        output_tokens: int,
    ) -> CostRecord:
        """Record an LLM call and update running total.

        Args:
            node: Which pipeline node made the call.
            input_tokens: Number of input tokens.
            output_tokens: Number of output tokens.

        Returns:
            The recorded CostRecord.
        """
        cost = self.estimate_cost(input_tokens, output_tokens)
        self._total_cost += cost

        record = CostRecord(
            node=node,
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=cost,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        self._records.append(record)
        return record

    def check_limit(self) -> bool:
        """Check if cost limit has been reached.

        Returns:
            True if total cost >= max_cost_usd.
        """
        return self._total_cost >= self.max_cost_usd

    def get_total(self) -> float:
        """Get current total cost.

        Returns:
            Total estimated cost in USD.
        """
        return self._total_cost

    def get_records(self) -> list[CostRecord]:
        """Get all recorded cost records.

        Returns:
            List of CostRecord dicts.
        """
        return list(self._records)

    def format_status(self) -> str:
        """Format cost status for display.

        Returns:
            String like '[cost] $X.XX / $Y.YY limit'.
        """
        return f"[cost] ${self._total_cost:.2f} / ${self.max_cost_usd:.2f} limit"


def count_tokens(text: str, model: str = "gpt-4o-mini") -> int:
    """Count tokens in text using tiktoken.

    Args:
        text: Text to tokenize.
        model: Model name for encoding selection.

    Returns:
        Number of tokens.
    """
    if not text:
        return 0
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    return len(encoding.encode(text))
