"""Batch-specific exception hierarchy."""


class BatchError(Exception):
    """Base exception for batch operations."""


class BatchInputError(BatchError):
    """Invalid batch input (target list, config, etc.)."""


class AllTokensExhaustedError(BatchError):
    """All tokens have hit their rate limit."""

    def __init__(self, wait_time: float) -> None:
        self.wait_time = wait_time
        super().__init__(f"All tokens exhausted. Next reset in {wait_time:.0f}s")


class InsufficientScopesError(BatchError):
    """Token lacks required GitHub API scopes."""

    def __init__(self, token_suffix: str, missing: list[str]) -> None:
        self.token_suffix = token_suffix
        self.missing = missing
        super().__init__(
            f"Token ...{token_suffix} missing scopes: {', '.join(missing)}"
        )


class RateLimitExhaustedError(BatchError):
    """Rate limit exhausted for a token, with wait time."""

    def __init__(self, wait_time: float) -> None:
        self.wait_time = wait_time
        super().__init__(f"Rate limit exhausted. Reset in {wait_time:.0f}s")
