"""Unit tests for redirect chain resolver with SSRF protection (LLD #20, §10.0).

TDD: Tests written BEFORE implementation.
Mock target: ``gh_link_auditor.redirect_resolver._http_head``
Covers: RedirectResolver.follow_redirects(), test_url_mutations(),
        verify_live(), _validate_not_private_ip(), SSRFBlocked
"""

from unittest.mock import patch

import pytest

from gh_link_auditor.redirect_resolver import RedirectResolver, SSRFBlocked

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_resolver() -> RedirectResolver:
    return RedirectResolver()


# ---------------------------------------------------------------------------
# T040: Redirect chain detection (REQ-3)
# ---------------------------------------------------------------------------


def _mock_public_dns(host, *args, **kwargs):
    """Mock DNS that always returns a public IP."""
    return [(2, 1, 6, "", ("93.184.216.34", 443))]


class TestFollowRedirects:
    def test_single_redirect(self):
        """Follow a single 301 redirect to final URL."""
        resolver = _make_resolver()

        def _mock_head(url):
            if url == "https://old.com/page":
                return {"status_code": 301, "location": "https://new.com/page"}
            return {"status_code": 200, "location": None}

        with (
            patch("gh_link_auditor.redirect_resolver._http_head", side_effect=_mock_head),
            patch("gh_link_auditor.redirect_resolver.socket.getaddrinfo", side_effect=_mock_public_dns),
        ):
            final_url, log = resolver.follow_redirects("https://old.com/page")
        assert final_url == "https://new.com/page"
        assert len(log) >= 1

    def test_multi_hop_redirect(self):
        """Follow a chain of 301 -> 302 -> 200."""
        resolver = _make_resolver()

        def _mock_head(url):
            if url == "https://a.com":
                return {"status_code": 301, "location": "https://b.com"}
            if url == "https://b.com":
                return {"status_code": 302, "location": "https://c.com"}
            return {"status_code": 200, "location": None}

        with (
            patch("gh_link_auditor.redirect_resolver._http_head", side_effect=_mock_head),
            patch("gh_link_auditor.redirect_resolver.socket.getaddrinfo", side_effect=_mock_public_dns),
        ):
            final_url, log = resolver.follow_redirects("https://a.com")
        assert final_url == "https://c.com"
        assert len(log) >= 2

    def test_no_redirect(self):
        """URL that returns 200 directly — no redirect."""
        resolver = _make_resolver()
        with (
            patch(
                "gh_link_auditor.redirect_resolver._http_head",
                return_value={"status_code": 200, "location": None},
            ),
            patch("gh_link_auditor.redirect_resolver.socket.getaddrinfo", side_effect=_mock_public_dns),
        ):
            final_url, log = resolver.follow_redirects("https://example.com")
        assert final_url is None  # No redirect happened
        assert isinstance(log, list)

    def test_max_redirects_limit(self):
        """Stop after MAX_REDIRECTS hops to prevent infinite loops."""
        resolver = _make_resolver()

        def _always_redirect(url):
            return {"status_code": 301, "location": f"{url}/next"}

        with (
            patch("gh_link_auditor.redirect_resolver._http_head", side_effect=_always_redirect),
            patch("gh_link_auditor.redirect_resolver.socket.getaddrinfo", side_effect=_mock_public_dns),
        ):
            final_url, log = resolver.follow_redirects("https://loop.com")
        assert final_url is None  # Gave up
        assert len(log) <= resolver.MAX_REDIRECTS + 1

    def test_redirect_404_returns_none(self):
        """Redirect landing on 404 returns None for final_url."""
        resolver = _make_resolver()

        def _mock_head(url):
            if url == "https://old.com":
                return {"status_code": 301, "location": "https://gone.com"}
            return {"status_code": 404, "location": None}

        with (
            patch("gh_link_auditor.redirect_resolver._http_head", side_effect=_mock_head),
            patch("gh_link_auditor.redirect_resolver.socket.getaddrinfo", side_effect=_mock_public_dns),
        ):
            final_url, log = resolver.follow_redirects("https://old.com")
        assert final_url is None

    def test_handles_307_308_redirects(self):
        """307 and 308 redirects are followed."""
        resolver = _make_resolver()

        def _mock_head(url):
            if url == "https://a.com":
                return {"status_code": 307, "location": "https://b.com"}
            if url == "https://b.com":
                return {"status_code": 308, "location": "https://c.com"}
            return {"status_code": 200, "location": None}

        with (
            patch("gh_link_auditor.redirect_resolver._http_head", side_effect=_mock_head),
            patch("gh_link_auditor.redirect_resolver.socket.getaddrinfo", side_effect=_mock_public_dns),
        ):
            final_url, log = resolver.follow_redirects("https://a.com")
        assert final_url == "https://c.com"


# ---------------------------------------------------------------------------
# T050: SSRF protection (REQ-8)
# ---------------------------------------------------------------------------


class TestSSRFProtection:
    def test_blocks_loopback(self):
        """127.0.0.1 blocked before connection."""
        resolver = _make_resolver()
        with patch(
            "gh_link_auditor.redirect_resolver.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("127.0.0.1", 443))],
        ):
            with pytest.raises(SSRFBlocked):
                resolver._validate_not_private_ip("localhost")

    def test_blocks_10_network(self):
        """10.x.x.x blocked."""
        resolver = _make_resolver()
        with patch(
            "gh_link_auditor.redirect_resolver.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("10.0.0.1", 443))],
        ):
            with pytest.raises(SSRFBlocked):
                resolver._validate_not_private_ip("internal.example.com")

    def test_blocks_172_16_network(self):
        """172.16.x.x blocked."""
        resolver = _make_resolver()
        with patch(
            "gh_link_auditor.redirect_resolver.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("172.16.0.1", 443))],
        ):
            with pytest.raises(SSRFBlocked):
                resolver._validate_not_private_ip("private.example.com")

    def test_blocks_192_168_network(self):
        """192.168.x.x blocked."""
        resolver = _make_resolver()
        with patch(
            "gh_link_auditor.redirect_resolver.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("192.168.1.1", 443))],
        ):
            with pytest.raises(SSRFBlocked):
                resolver._validate_not_private_ip("home.example.com")

    def test_blocks_link_local(self):
        """169.254.x.x blocked."""
        resolver = _make_resolver()
        with patch(
            "gh_link_auditor.redirect_resolver.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("169.254.0.1", 443))],
        ):
            with pytest.raises(SSRFBlocked):
                resolver._validate_not_private_ip("link-local.example.com")

    def test_allows_public_ip(self):
        """Public IP (93.184.216.34) is allowed."""
        resolver = _make_resolver()
        with patch(
            "gh_link_auditor.redirect_resolver.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("93.184.216.34", 443))],
        ):
            result = resolver._validate_not_private_ip("example.com")
        assert result is True

    def test_ssrf_in_redirect_chain(self):
        """SSRF blocked mid-redirect chain."""
        resolver = _make_resolver()

        def _mock_head(url):
            if url == "https://public.com":
                return {"status_code": 301, "location": "https://evil.com"}
            return {"status_code": 200, "location": None}

        with (
            patch("gh_link_auditor.redirect_resolver._http_head", side_effect=_mock_head),
            patch(
                "gh_link_auditor.redirect_resolver.socket.getaddrinfo",
                side_effect=lambda host, *a, **kw: (
                    [(2, 1, 6, "", ("93.184.216.34", 443))]
                    if host == "public.com"
                    else [(2, 1, 6, "", ("127.0.0.1", 443))]
                ),
            ),
        ):
            final_url, log = resolver.follow_redirects("https://public.com")
        assert final_url is None
        assert any("ssrf" in entry.lower() or "blocked" in entry.lower() for entry in log)


# ---------------------------------------------------------------------------
# T180: URL mutation detection (REQ-3)
# ---------------------------------------------------------------------------


class TestUrlMutations:
    def test_trailing_slash_mutation(self):
        """Tests adding/removing trailing slash."""
        resolver = _make_resolver()

        def _mock_head(url):
            if url == "https://example.com/docs/install/":
                return {"status_code": 200, "location": None}
            return {"status_code": 404, "location": None}

        with patch("gh_link_auditor.redirect_resolver._http_head", side_effect=_mock_head):
            mutations = resolver.test_url_mutations("https://example.com/docs/install")
        assert len(mutations) >= 1
        assert any("https://example.com/docs/install/" in m[0] for m in mutations)

    def test_http_to_https_mutation(self):
        """Tests http -> https upgrade."""
        resolver = _make_resolver()

        def _mock_head(url):
            if url == "https://example.com/page":
                return {"status_code": 200, "location": None}
            return {"status_code": 404, "location": None}

        with patch("gh_link_auditor.redirect_resolver._http_head", side_effect=_mock_head):
            mutations = resolver.test_url_mutations("http://example.com/page")
        assert any("https://example.com/page" in m[0] for m in mutations)

    def test_no_mutations_found(self):
        """Returns empty list when no mutations work."""
        resolver = _make_resolver()
        with patch(
            "gh_link_auditor.redirect_resolver._http_head",
            return_value={"status_code": 404, "location": None},
        ):
            mutations = resolver.test_url_mutations("https://example.com/nope")
        assert mutations == []


# ---------------------------------------------------------------------------
# verify_live
# ---------------------------------------------------------------------------


class TestVerifyLive:
    def test_live_url(self):
        resolver = _make_resolver()
        with patch(
            "gh_link_auditor.redirect_resolver._http_head",
            return_value={"status_code": 200, "location": None},
        ):
            assert resolver.verify_live("https://example.com") is True

    def test_dead_url(self):
        resolver = _make_resolver()
        with patch(
            "gh_link_auditor.redirect_resolver._http_head",
            return_value={"status_code": 404, "location": None},
        ):
            assert resolver.verify_live("https://example.com/gone") is False

    def test_error_returns_false(self):
        resolver = _make_resolver()
        with patch(
            "gh_link_auditor.redirect_resolver._http_head",
            side_effect=Exception("connection failed"),
        ):
            assert resolver.verify_live("https://example.com") is False
