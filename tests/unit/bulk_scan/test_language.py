"""Tests for bulk_scan.language (#238 — repo language detection)."""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx

from gh_link_auditor.bulk_scan import language

_ENGLISH = (
    "This is a comprehensive Python documentation example. "
    "It discusses libraries, frameworks, testing practices, and "
    "deployment patterns commonly used in production systems."
)
_CHINESE = (
    "这是一个中文文档示例。我们讨论 Python 编程语言、库和框架。这是一个详细的指南。"
    "包含安装、配置、使用方法和最佳实践。我们还介绍如何贡献代码和报告问题。"
    "这个项目使用 MIT 许可证。欢迎所有人参与开发。"
)
_JAPANESE = (
    "これは日本語のドキュメント例です。Python プログラミング言語、ライブラリ、テストについて説明します。"
    "インストール手順、設定方法、使用例、ベストプラクティスを含みます。"
    "このプロジェクトは MIT ライセンスのもとで公開されています。"
)
_RUSSIAN = (
    "Это документация на русском языке. Здесь обсуждаются Python, "
    "библиотеки и фреймворки, а также тестирование и развёртывание. "
    "Документ содержит инструкции по установке, настройке и использованию. "
    "Проект распространяется под лицензией MIT."
)


def _client_returning(status_code: int, text: str) -> MagicMock:
    client = MagicMock(spec=httpx.Client)
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text
    client.get.return_value = resp
    return client


def _client_with_per_url(responses: dict[str, tuple[int, str]]) -> MagicMock:
    client = MagicMock(spec=httpx.Client)

    def _get(url, **_kwargs):  # type: ignore[no-untyped-def]
        for key, (status, text) in responses.items():
            if url.endswith(key):
                resp = MagicMock(spec=httpx.Response)
                resp.status_code = status
                resp.text = text
                return resp
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 404
        resp.text = ""
        return resp

    client.get.side_effect = _get
    return client


class TestDetectRepoLanguage:
    def test_english_readme(self) -> None:
        client = _client_returning(200, _ENGLISH)
        assert language.detect_repo_language("any/repo", client=client) == "en"

    def test_chinese_readme(self) -> None:
        client = _client_returning(200, _CHINESE)
        result = language.detect_repo_language("any/repo", client=client)
        # langdetect uses zh-cn or zh-tw; we only assert it's a zh-* code
        assert result is not None and result.startswith("zh")

    def test_japanese_readme(self) -> None:
        client = _client_returning(200, _JAPANESE)
        assert language.detect_repo_language("any/repo", client=client) == "ja"

    def test_russian_readme(self) -> None:
        client = _client_returning(200, _RUSSIAN)
        assert language.detect_repo_language("any/repo", client=client) == "ru"

    def test_all_variants_404(self) -> None:
        client = _client_returning(404, "")
        assert language.detect_repo_language("any/repo", client=client) is None

    def test_short_text_returns_none(self) -> None:
        # Below MIN_TEXT_LEN — should skip without raising
        client = _client_returning(200, "tiny")
        assert language.detect_repo_language("any/repo", client=client) is None

    def test_falls_through_to_next_variant(self) -> None:
        # README.md is 404, README.rst is 200 with English
        client = _client_with_per_url(
            {
                "README.md": (404, ""),
                "README.rst": (200, _ENGLISH),
            }
        )
        assert language.detect_repo_language("any/repo", client=client) == "en"

    def test_http_error_returns_none(self) -> None:
        client = MagicMock(spec=httpx.Client)
        client.get.side_effect = httpx.ConnectError("boom")
        assert language.detect_repo_language("any/repo", client=client) is None

    def test_empty_body_skipped(self) -> None:
        client = _client_returning(200, "")
        assert language.detect_repo_language("any/repo", client=client) is None
