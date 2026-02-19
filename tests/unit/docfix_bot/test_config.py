"""Tests for docfix_bot.config."""

from __future__ import annotations

from docfix_bot.config import (
    configure_logging,
    get_default_config,
    get_http_timeout,
    get_user_agent,
)


class TestGetDefaultConfig:
    def test_returns_dict(self) -> None:
        config = get_default_config()
        assert isinstance(config, dict)

    def test_has_required_keys(self) -> None:
        config = get_default_config()
        assert "github_token" in config
        assert "http_timeout" in config
        assert "max_prs_per_day" in config

    def test_returns_copy(self) -> None:
        c1 = get_default_config()
        c2 = get_default_config()
        c1["github_token"] = "modified"
        assert c2["github_token"] == ""


class TestGetUserAgent:
    def test_default(self) -> None:
        config = get_default_config()
        ua = get_user_agent(config)
        assert "DocFixBot" in ua

    def test_custom(self) -> None:
        config = {"user_agent": "Custom/1.0"}
        ua = get_user_agent(config)
        assert ua == "Custom/1.0"

    def test_fallback(self) -> None:
        ua = get_user_agent({})
        assert "DocFixBot" in ua


class TestGetHttpTimeout:
    def test_default(self) -> None:
        config = get_default_config()
        timeout = get_http_timeout(config)
        assert timeout == 10.0

    def test_custom(self) -> None:
        timeout = get_http_timeout({"http_timeout": 5.0})
        assert timeout == 5.0

    def test_fallback(self) -> None:
        timeout = get_http_timeout({})
        assert timeout == 10.0


class TestConfigureLogging:
    def test_does_not_raise(self) -> None:
        configure_logging()
