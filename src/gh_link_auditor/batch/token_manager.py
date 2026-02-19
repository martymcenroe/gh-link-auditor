"""Token pool with rotation, scope validation, and rate-limit tracking.

See LLD-019 §2.4 for TokenManager specification.
"""

from __future__ import annotations

import logging
import os
import stat
from datetime import datetime, timezone
from pathlib import Path

import httpx

from gh_link_auditor.batch.exceptions import (
    AllTokensExhaustedError,
    InsufficientScopesError,
)
from gh_link_auditor.batch.models import TokenState

logger = logging.getLogger(__name__)

REQUIRED_SCOPES = {"repo", "public_repo"}


class TokenManager:
    """Manages a pool of GitHub tokens with rotation and validation."""

    def __init__(self, tokens: list[str]) -> None:
        """Initialize with one or more GitHub tokens.

        Args:
            tokens: List of GitHub PAT strings.
        """
        self._states: list[TokenState] = [TokenState(token=t) for t in tokens]

    async def validate_all(self) -> list[TokenState]:
        """Validate scopes and rate limits for all tokens.

        Returns:
            List of validated TokenState objects.

        Raises:
            InsufficientScopesError: If any token lacks required scopes.
        """
        for ts in self._states:
            headers = {
                "Authorization": f"Bearer {ts.token}",
                "Accept": "application/vnd.github+json",
            }
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        "https://api.github.com/rate_limit",
                        headers=headers,
                        timeout=10.0,
                    )
                if resp.status_code == 401:
                    ts.is_valid = False
                    continue

                # Parse scopes from response header
                scope_header = resp.headers.get("X-OAuth-Scopes", "")
                ts.scopes = [s.strip() for s in scope_header.split(",") if s.strip()]

                # Check required scopes
                has_scopes = set(ts.scopes)
                missing = REQUIRED_SCOPES - has_scopes
                if missing:
                    suffix = ts.token[-4:] if len(ts.token) >= 4 else "****"
                    raise InsufficientScopesError(suffix, sorted(missing))

                # Parse rate limit info
                remaining_str = resp.headers.get("X-RateLimit-Remaining", "")
                if remaining_str:
                    ts.remaining = int(remaining_str)
                reset_str = resp.headers.get("X-RateLimit-Reset", "")
                if reset_str:
                    ts.reset_at = datetime.fromtimestamp(
                        int(reset_str), tz=timezone.utc
                    )

            except httpx.HTTPError:
                ts.is_valid = False

        return self._states

    def get_best_token(self) -> TokenState:
        """Return the token with the most remaining rate limit headroom.

        Returns:
            TokenState with highest remaining.

        Raises:
            AllTokensExhaustedError: If no valid tokens available.
        """
        valid = [ts for ts in self._states if ts.is_valid]
        if not valid:
            raise AllTokensExhaustedError(wait_time=0.0)

        # Sort by remaining descending
        valid.sort(key=lambda ts: ts.remaining, reverse=True)
        best = valid[0]

        if best.remaining == 0 and best.reset_at:
            now = datetime.now(timezone.utc)
            wait = max((best.reset_at - now).total_seconds(), 0.0)
            raise AllTokensExhaustedError(wait_time=wait)

        return best

    def update_token_state(self, token: str, headers: dict[str, str]) -> None:
        """Update a token's rate limit state from response headers.

        Args:
            token: The token string.
            headers: Response headers with X-RateLimit-* values.
        """
        for ts in self._states:
            if ts.token == token:
                remaining_str = headers.get("X-RateLimit-Remaining", "")
                if remaining_str:
                    ts.remaining = int(remaining_str)
                reset_str = headers.get("X-RateLimit-Reset", "")
                if reset_str:
                    ts.reset_at = datetime.fromtimestamp(
                        int(reset_str), tz=timezone.utc
                    )
                break

    def invalidate_token(self, token: str) -> None:
        """Mark a token as invalid (e.g., after 401 response).

        Args:
            token: The token string to invalidate.
        """
        for ts in self._states:
            if ts.token == token:
                ts.is_valid = False
                break


def load_tokens_from_file(path: Path) -> list[str]:
    """Load tokens from a file (one per line).

    Args:
        path: Path to token file.

    Returns:
        List of token strings.
    """
    check_token_file_permissions(path)
    text = path.read_text().strip()
    return [line.strip() for line in text.splitlines() if line.strip()]


def load_tokens_from_env() -> list[str]:
    """Load tokens from GITHUB_TOKEN environment variable.

    Returns:
        List with single token, or empty list.
    """
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        return [token]
    return []


def check_token_file_permissions(path: Path) -> None:
    """Warn if token file has overly permissive permissions.

    Args:
        path: Path to token file.
    """
    try:
        st = path.stat()
        mode = st.st_mode
        # Check if group or others have read access
        if mode & (stat.S_IRGRP | stat.S_IROTH):
            logger.warning(
                "Token file %s has overly permissive permissions (mode=%o). "
                "Consider restricting to owner-only (chmod 600).",
                path,
                stat.S_IMODE(mode),
            )
    except OSError:
        pass
