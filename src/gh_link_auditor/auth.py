"""GitHub token resolution with gh CLI fallback.

Resolves GITHUB_TOKEN from environment first, then falls back to
``gh auth token`` via subprocess. The subprocess output stays internal
to Python and never reaches Claude's stdout.
"""

from __future__ import annotations

import os
import subprocess


def resolve_github_token() -> str:
    """Resolve a GitHub token from environment or gh CLI.

    Priority:
        1. ``GITHUB_TOKEN`` environment variable
        2. ``gh auth token`` subprocess (silent, captured)

    Returns:
        The token string, or empty string if unavailable.
    """
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        return token

    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            token = result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return token
