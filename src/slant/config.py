"""Configurable signal weights for Slant scoring engine.

Provides default weights and optional JSON config file loading.

See LLD #21 §2.4 for specification.
"""

from __future__ import annotations

import json
from pathlib import Path

from slant.models import SignalWeights


def get_default_weights() -> SignalWeights:
    """Return default signal weights (redirect=40, title=25, content=20, url_path=10, domain=5).

    Returns:
        SignalWeights with default values summing to 100.
    """
    return SignalWeights(
        redirect=40,
        title=25,
        content=20,
        url_path=10,
        domain=5,
    )


def load_weights(config_path: Path | None = None) -> SignalWeights:
    """Load weights from JSON config file or return defaults.

    Args:
        config_path: Path to JSON config file, or None for defaults.

    Returns:
        SignalWeights loaded from file or defaults.
    """
    if config_path is None:
        return get_default_weights()

    try:
        data = json.loads(config_path.read_text())
        return SignalWeights(
            redirect=data.get("redirect", 40),
            title=data.get("title", 25),
            content=data.get("content", 20),
            url_path=data.get("url_path", 10),
            domain=data.get("domain", 5),
        )
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return get_default_weights()
