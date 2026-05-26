"""Tests for ``gh_link_auditor.domain_rebrand`` (#262)."""

from __future__ import annotations

import pytest

from gh_link_auditor.domain_rebrand import (
    SUNSET_DOMAINS,
    SunsetEntry,
    find_rebrand_target,
    find_sunset_entry,
    is_sunsetted_host,
)


class TestFindRebrandTarget:
    def test_picoctf_to_cylab(self) -> None:
        """The motivating example from the #262 audit observation."""
        target = find_rebrand_target("https://play.picoctf.org/challenges/cryptography")
        assert target == "https://learn.cylabacademy.org/challenges/cryptography"

    def test_path_with_query_and_fragment_preserved(self) -> None:
        target = find_rebrand_target("https://gitter.im/some-org/room?utm=x#anchor")
        assert target == "https://element.io/some-org/room?utm=x#anchor"

    def test_signalfx_subdomain(self) -> None:
        """The docs.signalfx.com case from the audit."""
        target = find_rebrand_target("https://docs.signalfx.com/en/latest/index.html")
        assert target == "https://docs.splunk.com/en/latest/index.html"

    def test_scheme_preserved(self) -> None:
        target = find_rebrand_target("http://gitter.im/foo/bar")
        assert target == "http://element.io/foo/bar"

    def test_unknown_host_returns_none(self) -> None:
        assert find_rebrand_target("https://this-domain-is-fine.example/anywhere") is None

    def test_host_case_insensitive(self) -> None:
        """Hosts are case-insensitive per RFC; sunset table matches that."""
        target = find_rebrand_target("https://GITTER.IM/path")
        assert target == "https://element.io/path"

    def test_root_path(self) -> None:
        target = find_rebrand_target("https://gitter.im")
        # urlparse on a URL with no path yields path="" -- preserved as such.
        assert target == "https://element.io"

    def test_no_successor_returns_none(self) -> None:
        """hipchat.com shut down with no replacement; no candidate URL
        can be synthesized."""
        assert find_rebrand_target("https://hipchat.com/sign_in") is None

    def test_invalid_url_returns_none(self) -> None:
        assert find_rebrand_target("not-a-url") is None

    def test_url_without_host_returns_none(self) -> None:
        assert find_rebrand_target("https://") is None


class TestFindSunsetEntry:
    def test_returns_entry_for_known_host(self) -> None:
        entry = find_sunset_entry("https://play.picoctf.org/x")
        assert isinstance(entry, SunsetEntry)
        assert entry.old_host == "play.picoctf.org"
        assert entry.replacement_host == "learn.cylabacademy.org"
        assert entry.since == "2023"

    def test_returns_entry_with_none_replacement(self) -> None:
        """No-successor case -- entry is still returned so the operator
        can see the diagnostic."""
        entry = find_sunset_entry("https://gfycat.com/something")
        assert entry is not None
        assert entry.replacement_host is None
        assert "shutdown" in entry.reason.lower()

    def test_unknown_host_returns_none(self) -> None:
        assert find_sunset_entry("https://wikipedia.org/wiki/x") is None

    def test_invalid_url_returns_none(self) -> None:
        assert find_sunset_entry("not-a-url") is None


class TestIsSunsetted:
    def test_known_host_returns_true(self) -> None:
        assert is_sunsetted_host("https://play.picoctf.org/x") is True

    def test_known_no_successor_host_returns_true(self) -> None:
        """is_sunsetted is host-presence; replacement-availability is
        find_rebrand_target's concern. A shut-down host IS sunsetted."""
        assert is_sunsetted_host("https://hipchat.com/x") is True

    def test_unknown_host_returns_false(self) -> None:
        assert is_sunsetted_host("https://github.com/x") is False


class TestSunsetTableShape:
    """Pin invariants on the table so a future addition can't subtly
    break the contract."""

    @pytest.mark.parametrize("host,entry", list(SUNSET_DOMAINS.items()))
    def test_table_keys_match_old_host_field(self, host: str, entry: SunsetEntry) -> None:
        """The dict key must equal the entry's ``old_host`` so lookups
        and diagnostics stay consistent."""
        assert host == entry.old_host

    @pytest.mark.parametrize("host,entry", list(SUNSET_DOMAINS.items()))
    def test_host_is_lowercase(self, host: str, entry: SunsetEntry) -> None:
        """The lookup normalizes input to lowercase; table entries must
        also be lowercase."""
        assert host == host.lower()

    @pytest.mark.parametrize("host,entry", list(SUNSET_DOMAINS.items()))
    def test_entry_has_since_year(self, host: str, entry: SunsetEntry) -> None:
        """Every entry must record when the rebrand happened so the
        operator can sanity-check (if the rebrand was 10+ years ago and
        we never noticed, the corpus probably has bigger problems)."""
        assert entry.since
        # 4-digit year sanity check
        assert entry.since.isdigit() and len(entry.since) == 4

    @pytest.mark.parametrize("host,entry", list(SUNSET_DOMAINS.items()))
    def test_no_successor_entries_have_reason(self, host: str, entry: SunsetEntry) -> None:
        """If there's no replacement_host the operator needs to know why
        (shutdown? bought and content deleted?) -- the reason field is
        load-bearing for the no-successor case."""
        if entry.replacement_host is None:
            assert entry.reason
