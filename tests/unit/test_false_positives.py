"""Tests for false positive knowledge store.

See Issues #94, #97 for specification.
"""

from __future__ import annotations

from gh_link_auditor.false_positives import (
    is_api_test_endpoint,
    is_bot_blocked,
    is_false_positive,
    is_github_auth_required,
    is_github_issue_404,
    is_placeholder_path,
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

    def test_wikimedia_429(self) -> None:
        assert is_bot_blocked("https://upload.wikimedia.org/wikipedia/commons/image.png", 429) is True

    def test_wikipedia_429(self) -> None:
        assert is_bot_blocked("https://en.wikipedia.org/wiki/Python", 429) is True

    def test_stackoverflow_429(self) -> None:
        assert is_bot_blocked("https://stackoverflow.com/q/1", 429) is True

    def test_random_site_429_not_blocked(self) -> None:
        assert is_bot_blocked("https://random-site.com/page", 429) is False

    def test_medium_403(self) -> None:
        assert is_bot_blocked("https://medium.com/@user/article-123", 403) is True

    def test_quora_403(self) -> None:
        assert is_bot_blocked("https://www.quora.com/What-is-something", 403) is True

    def test_sciencedirect_403(self) -> None:
        assert is_bot_blocked("https://www.sciencedirect.com/topics/computer-science/x", 403) is True

    def test_investopedia_403(self) -> None:
        assert is_bot_blocked("https://www.investopedia.com/", 403) is True


class TestIsApiTestEndpoint:
    """Tests for is_api_test_endpoint()."""

    def test_httpbin_org(self) -> None:
        assert is_api_test_endpoint("https://httpbin.org/get") is True

    def test_httpbin_org_auth(self) -> None:
        assert is_api_test_endpoint("https://httpbin.org/basic-auth/user/pass") is True

    def test_httpbin_org_status(self) -> None:
        assert is_api_test_endpoint("https://httpbin.org/status/404") is True

    def test_httpbin_com(self) -> None:
        assert is_api_test_endpoint("https://httpbin.com/get") is True

    def test_real_api_not_test(self) -> None:
        assert is_api_test_endpoint("https://api.github.com/events") is False

    def test_empty(self) -> None:
        assert is_api_test_endpoint("") is False


class TestIsPlaceholderPath:
    """Tests for is_placeholder_path()."""

    def test_your_username(self) -> None:
        assert is_placeholder_path("https://github.com/YOUR-USERNAME/httpx") is True

    def test_your_username_underscore(self) -> None:
        assert is_placeholder_path("https://github.com/YOUR_USERNAME/repo") is True

    def test_your_org(self) -> None:
        assert is_placeholder_path("https://github.com/YOUR-ORG/repo") is True

    def test_your_repo(self) -> None:
        assert is_placeholder_path("https://example.com/YOUR-REPO/path") is True

    def test_your_token(self) -> None:
        assert is_placeholder_path("https://api.example.com/YOUR-TOKEN/data") is True

    def test_username_placeholder(self) -> None:
        assert is_placeholder_path("https://github.com/USERNAME/repo") is True

    def test_owner_placeholder(self) -> None:
        assert is_placeholder_path("https://github.com/OWNER/repo") is True

    def test_case_insensitive(self) -> None:
        assert is_placeholder_path("https://github.com/your-username/repo") is True

    def test_real_username_not_placeholder(self) -> None:
        assert is_placeholder_path("https://github.com/pallets/flask") is False

    def test_real_path(self) -> None:
        assert is_placeholder_path("https://docs.python.org/3/library/") is False


class TestIsGithubIssue404:
    """Tests for is_github_issue_404()."""

    def test_issue_404(self) -> None:
        assert is_github_issue_404("https://github.com/encode/httpx/issues/1434", 404) is True

    def test_pr_404(self) -> None:
        assert is_github_issue_404("https://github.com/org/repo/pull/123", 404) is True

    def test_issue_200(self) -> None:
        assert is_github_issue_404("https://github.com/encode/httpx/issues/1", 200) is False

    def test_issue_403(self) -> None:
        assert is_github_issue_404("https://github.com/encode/httpx/issues/1", 403) is False

    def test_not_github(self) -> None:
        assert is_github_issue_404("https://gitlab.com/org/repo/issues/1", 404) is False

    def test_github_repo_404(self) -> None:
        # Repo-level 404 is NOT an issue/PR — could be genuinely deleted
        assert is_github_issue_404("https://github.com/org/deleted-repo", 404) is False

    def test_none_status(self) -> None:
        assert is_github_issue_404("https://github.com/org/repo/issues/1", None) is False


class TestIsGithubAuthRequired:
    """Tests for is_github_auth_required()."""

    def test_issues_new(self) -> None:
        assert is_github_auth_required("https://github.com/encode/httpx/issues/new", 404) is True

    def test_compare(self) -> None:
        assert is_github_auth_required("https://github.com/org/repo/compare", 404) is True

    def test_settings(self) -> None:
        assert is_github_auth_required("https://github.com/org/repo/settings", 404) is True

    def test_releases_new(self) -> None:
        assert is_github_auth_required("https://github.com/org/repo/releases/new", 404) is True

    def test_not_404(self) -> None:
        assert is_github_auth_required("https://github.com/org/repo/issues/new", 200) is False

    def test_regular_issue_not_auth(self) -> None:
        # Regular issue paths are handled by is_github_issue_404, not this
        assert is_github_auth_required("https://github.com/org/repo/issues/123", 404) is False

    def test_non_github(self) -> None:
        assert is_github_auth_required("https://gitlab.com/org/repo/issues/new", 404) is False


class TestIsFalsePositive:
    """Tests for is_false_positive() master check."""

    def test_placeholder_domain(self) -> None:
        assert is_false_positive("https://example.com/page") is True

    def test_placeholder_path(self) -> None:
        assert is_false_positive("https://github.com/YOUR-USERNAME/repo") is True

    def test_api_test_endpoint(self) -> None:
        assert is_false_positive("https://httpbin.org/get") is True

    def test_bot_blocked(self) -> None:
        assert is_false_positive("https://stackoverflow.com/q/1", http_status=403) is True

    def test_github_issue_404(self) -> None:
        assert is_false_positive("https://github.com/org/repo/issues/999", http_status=404) is True

    def test_real_dead_link(self) -> None:
        assert is_false_positive("https://old-dead-site.com/page", http_status=404) is False

    def test_real_site_403(self) -> None:
        assert is_false_positive("https://some-api.com/endpoint", http_status=403) is False

    def test_bot_blocked_without_status(self) -> None:
        assert is_false_positive("https://stackoverflow.com/q/1") is False

    def test_github_auth_required(self) -> None:
        assert is_false_positive("https://github.com/org/repo/issues/new", http_status=404) is True

    def test_wikimedia_429(self) -> None:
        assert is_false_positive("https://upload.wikimedia.org/image.png", http_status=429) is True

    def test_github_repo_404_not_filtered(self) -> None:
        # Deleted repos ARE real dead links
        assert is_false_positive("https://github.com/org/deleted-repo", http_status=404) is False
