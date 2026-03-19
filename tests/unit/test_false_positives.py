"""Tests for false positive knowledge store.

See Issue #94 for specification.
"""

from __future__ import annotations

from gh_link_auditor.false_positives import (
    is_bot_blocked,
    is_false_positive,
    is_placeholder_url,
)


class TestIsPlaceholderUrl:
    """Tests for is_placeholder_url()."""

    def test_example_com(self) -> None:
        assert is_placeholder_url("https://example.com/myapp/") is True

    def test_example_org(self) -> None:
        assert is_placeholder_url("http://example.org/page") is True

    def test_example_net(self) -> None:
        assert is_placeholder_url("https://example.net") is True

    def test_example_edu(self) -> None:
        assert is_placeholder_url("https://example.edu/course") is True

    def test_subdomain_of_example(self) -> None:
        assert is_placeholder_url("https://www.example.com/page") is True

    def test_deep_subdomain(self) -> None:
        assert is_placeholder_url("https://api.v2.example.com/data") is True

    def test_localhost(self) -> None:
        assert is_placeholder_url("http://localhost:8080/api") is True

    def test_127_0_0_1(self) -> None:
        assert is_placeholder_url("http://127.0.0.1/test") is True

    def test_real_domain_not_placeholder(self) -> None:
        assert is_placeholder_url("https://flask.palletsprojects.com/") is False

    def test_github_not_placeholder(self) -> None:
        assert is_placeholder_url("https://github.com/pallets/flask") is False

    def test_empty_string(self) -> None:
        assert is_placeholder_url("") is False

    def test_not_a_url(self) -> None:
        assert is_placeholder_url("not-a-url") is False

    def test_domain_containing_example_but_not_matching(self) -> None:
        assert is_placeholder_url("https://myexample.com/page") is False

    def test_example_in_path_not_domain(self) -> None:
        assert is_placeholder_url("https://docs.python.org/example") is False

    def test_malformed_url(self) -> None:
        assert is_placeholder_url("://broken") is False


class TestIsBotBlocked:
    """Tests for is_bot_blocked()."""

    def test_stackoverflow_403(self) -> None:
        assert is_bot_blocked("https://stackoverflow.com/q/12345", 403) is True

    def test_stackexchange_403(self) -> None:
        assert is_bot_blocked("https://security.stackexchange.com/q/39118", 403) is True

    def test_serverfault_403(self) -> None:
        assert is_bot_blocked("https://serverfault.com/q/100", 403) is True

    def test_askubuntu_403(self) -> None:
        assert is_bot_blocked("https://askubuntu.com/q/200", 403) is True

    def test_stackoverflow_404_not_blocked(self) -> None:
        assert is_bot_blocked("https://stackoverflow.com/q/12345", 404) is False

    def test_stackoverflow_200_not_blocked(self) -> None:
        assert is_bot_blocked("https://stackoverflow.com/q/12345", 200) is False

    def test_unknown_domain_403(self) -> None:
        assert is_bot_blocked("https://random-site.com/page", 403) is False

    def test_github_403(self) -> None:
        assert is_bot_blocked("https://github.com/repo", 403) is False

    def test_none_status(self) -> None:
        assert is_bot_blocked("https://stackoverflow.com/q/1", None) is False

    def test_subdomain_match(self) -> None:
        assert is_bot_blocked("https://meta.stackoverflow.com/q/1", 403) is True

    def test_malformed_url(self) -> None:
        assert is_bot_blocked("://broken", 403) is False


class TestIsFalsePositive:
    """Tests for is_false_positive() master check."""

    def test_placeholder_is_false_positive(self) -> None:
        assert is_false_positive("https://example.com/page") is True

    def test_placeholder_without_status(self) -> None:
        assert is_false_positive("https://example.com/page", http_status=None) is True

    def test_bot_blocked_is_false_positive(self) -> None:
        assert is_false_positive("https://stackoverflow.com/q/1", http_status=403) is True

    def test_real_dead_link_not_false_positive(self) -> None:
        assert is_false_positive("https://old-dead-site.com/page", http_status=404) is False

    def test_real_site_403_not_false_positive(self) -> None:
        assert is_false_positive("https://some-api.com/endpoint", http_status=403) is False

    def test_bot_blocked_without_status_not_triggered(self) -> None:
        assert is_false_positive("https://stackoverflow.com/q/1") is False
