"""Configuration management for Doc-Fix Bot.

See LLD #2 §2.4 for config specification.
Deviation: uses stdlib logging instead of structlog to match codebase conventions.
"""

from __future__ import annotations

import logging

from docfix_bot.models import BotConfig

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG: BotConfig = {
    "github_token": "",
    "user_agent": "DocFixBot/1.0 (+https://github.com/martymcenroe/gh-link-auditor)",
    "http_timeout": 10.0,
    "max_prs_per_day": 10,
    "max_api_calls_per_hour": 500,
    "min_fix_confidence": 0.8,
    "targets_path": "data/config/targets.yaml",
    "blocklist_path": "data/config/blocklist.yaml",
    "state_db_path": "data/state/docfix_state.json",
}


def get_default_config() -> BotConfig:
    """Return a copy of the default bot configuration.

    Returns:
        Default BotConfig.
    """
    return dict(_DEFAULT_CONFIG)  # type: ignore[return-value]


def get_user_agent(config: BotConfig) -> str:
    """Return the User-Agent string.

    Args:
        config: Bot configuration.

    Returns:
        User-Agent string.
    """
    return config.get("user_agent", _DEFAULT_CONFIG["user_agent"])


def get_http_timeout(config: BotConfig) -> float:
    """Return HTTP read timeout in seconds.

    Args:
        config: Bot configuration.

    Returns:
        Timeout in seconds.
    """
    return config.get("http_timeout", 10.0)


def configure_logging(level: int = logging.INFO) -> None:
    """Configure logging for Doc-Fix Bot.

    Args:
        level: Logging level.
    """
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
