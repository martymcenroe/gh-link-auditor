"""Unit tests for maintainer policy checker (LLD #4, §10.0).

TDD: Tests written BEFORE implementation. All tests should be RED until
policy_checker.py is implemented.

Mock target for HTTP fetching: ``policy_checker.network_check_url``
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from gh_link_auditor.policy_checker import (
    PolicyCheckResult,
    PolicyKeyword,
    PolicyStatus,
    check_repository_policy,
    determine_block_status,
    fetch_contributing_content,
    parse_policy_keywords,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "contributing_samples"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_fixture(name: str) -> str:
    """Read a fixture file and return its content."""
    return (FIXTURES / name).read_text(encoding="utf-8")


def _mock_fetch_result(content: str | None, status_code: int = 200):
    """Build a network RequestResult for mocking fetch_contributing_content."""
    from gh_link_auditor.network import RequestResult

    if content is None:
        return RequestResult(
            url="https://raw.githubusercontent.com/org/repo/HEAD/CONTRIBUTING.md",
            status="error",
            status_code=404,
            method="GET",
            response_time_ms=50,
            retries=0,
            error="HTTP 404",
        )
    return RequestResult(
        url="https://raw.githubusercontent.com/org/repo/HEAD/CONTRIBUTING.md",
        status="ok",
        status_code=status_code,
        method="GET",
        response_time_ms=50,
        retries=0,
        error=None,
    )


# ---------------------------------------------------------------------------
# T010: Check CONTRIBUTING.md exists before scanning (REQ-1)
# ---------------------------------------------------------------------------


class TestFetchContributing:
    # T010
    def test_check_contributing_file_exists(self):
        """Verifies that fetch_contributing_content returns content when file exists."""
        content = _read_fixture("contributing_clean.md")
        with patch(
            "gh_link_auditor.policy_checker._fetch_raw_url",
            return_value=content,
        ):
            result = fetch_contributing_content("https://github.com/org/repo")
        assert result is not None
        assert "Contributing" in result

    # T100: Fetch when file missing proceeds with scan (REQ-6)
    def test_fetch_contributing_not_found_proceeds(self):
        """Returns None and allows scan when CONTRIBUTING.md missing."""
        with patch(
            "gh_link_auditor.policy_checker._fetch_raw_url",
            return_value=None,
        ):
            result = fetch_contributing_content("https://github.com/org/repo")
        assert result is None

    # T140: Fetch from root location (REQ-1)
    def test_fetch_contributing_root(self):
        """Fetches from root /CONTRIBUTING.md location."""
        content = _read_fixture("contributing_clean.md")
        with patch(
            "gh_link_auditor.policy_checker._fetch_raw_url",
            side_effect=lambda url: content if "CONTRIBUTING.md" in url else None,
        ):
            result = fetch_contributing_content("https://github.com/org/repo")
        assert result is not None

    # T150: Fetch from .github location (REQ-1)
    def test_fetch_contributing_github_dir(self):
        """Fetches from .github/CONTRIBUTING.md when root not found."""
        content = _read_fixture("contributing_clean.md")

        def _side_effect(url):
            if ".github/CONTRIBUTING.md" in url:
                return content
            return None

        with patch(
            "gh_link_auditor.policy_checker._fetch_raw_url",
            side_effect=_side_effect,
        ):
            result = fetch_contributing_content("https://github.com/org/repo")
        assert result is not None


# ---------------------------------------------------------------------------
# T020–T060: Parse individual keywords (REQ-2)
# ---------------------------------------------------------------------------


class TestParseKeywords:
    # T020
    def test_parse_no_bot_keyword(self):
        content = _read_fixture("contributing_no_bot.md")
        keywords = parse_policy_keywords(content)
        assert PolicyKeyword.NO_BOT in keywords

    # T030
    def test_parse_no_pr_keyword(self):
        content = "We do not accept PRs from bots. no-pr policy applies."
        keywords = parse_policy_keywords(content)
        assert PolicyKeyword.NO_PR in keywords

    # T040
    def test_parse_typos_welcome_keyword(self):
        content = _read_fixture("contributing_welcome.md")
        keywords = parse_policy_keywords(content)
        assert PolicyKeyword.TYPOS_WELCOME in keywords

    # T050
    def test_parse_skip_doc_prs_keyword(self):
        content = "Please skip-doc-prs — we handle docs internally."
        keywords = parse_policy_keywords(content)
        assert PolicyKeyword.SKIP_DOC_PRS in keywords

    # T060
    def test_parse_contact_first_keyword(self):
        content = _read_fixture("contributing_contact.md")
        keywords = parse_policy_keywords(content)
        assert PolicyKeyword.CONTACT_FIRST in keywords

    # T090: Case insensitive matching (REQ-5)
    def test_parse_case_insensitive(self):
        content = "Policy: NO-BOT. Also No-Bot and no-bot."
        keywords = parse_policy_keywords(content)
        assert PolicyKeyword.NO_BOT in keywords

    # T110: No keywords in content (REQ-2)
    def test_parse_no_keywords(self):
        content = _read_fixture("contributing_clean.md")
        keywords = parse_policy_keywords(content)
        assert keywords == []


# ---------------------------------------------------------------------------
# T070, T120, T130: Determine block status (REQ-3)
# ---------------------------------------------------------------------------


class TestDetermineBlockStatus:
    # T070
    def test_determine_blocked_for_blocking_keyword(self):
        is_blocked, reason = determine_block_status([PolicyKeyword.NO_BOT])
        assert is_blocked is True
        assert reason is not None
        assert "no-bot" in reason.lower() or "no_bot" in reason.lower()

    # T120
    def test_determine_allowed_typos_welcome(self):
        is_blocked, reason = determine_block_status([PolicyKeyword.TYPOS_WELCOME])
        assert is_blocked is False
        assert reason is None

    # T130: Mixed keywords — blocking wins (REQ-3)
    def test_determine_blocked_mixed(self):
        is_blocked, reason = determine_block_status(
            [PolicyKeyword.TYPOS_WELCOME, PolicyKeyword.NO_BOT]
        )
        assert is_blocked is True


# ---------------------------------------------------------------------------
# T080: Log blacklisted result (REQ-4)
# ---------------------------------------------------------------------------


class TestLogPolicyResult:
    # T080
    def test_log_policy_blacklisted_status(self):
        """Blocked result is logged to state database as policy-blacklisted."""
        mock_db = MagicMock()
        result = PolicyCheckResult(
            repo_url="https://github.com/org/repo",
            contributing_found=True,
            contributing_path="CONTRIBUTING.md",
            keywords_found=[PolicyKeyword.NO_BOT],
            is_blocked=True,
            block_reason="no-bot policy",
            status=PolicyStatus.BLOCKED,
        )
        # Import here so we can call the logging function
        from gh_link_auditor.policy_checker import log_policy_result

        log_policy_result(result, mock_db)
        mock_db.add_to_blacklist.assert_called_once()
        call_kwargs = mock_db.add_to_blacklist.call_args
        assert "policy" in str(call_kwargs).lower()


# ---------------------------------------------------------------------------
# T160, T170: Full flow integration (REQ-3, REQ-4, REQ-6)
# ---------------------------------------------------------------------------


class TestCheckRepositoryPolicy:
    # T160: Full flow — blocked repo
    def test_check_repository_policy_blocked(self):
        content = _read_fixture("contributing_no_bot.md")
        with patch(
            "gh_link_auditor.policy_checker._fetch_raw_url",
            return_value=content,
        ):
            result = check_repository_policy("https://github.com/org/repo")
        assert result["is_blocked"] is True
        assert result["status"] == PolicyStatus.BLOCKED
        assert result["contributing_found"] is True

    # T170: Full flow — allowed repo
    def test_check_repository_policy_allowed(self):
        content = _read_fixture("contributing_welcome.md")
        with patch(
            "gh_link_auditor.policy_checker._fetch_raw_url",
            return_value=content,
        ):
            result = check_repository_policy("https://github.com/org/repo")
        assert result["is_blocked"] is False
        assert result["status"] == PolicyStatus.ALLOWED

    def test_check_repository_policy_unknown_no_file(self):
        """When no CONTRIBUTING.md found, status is UNKNOWN and scan proceeds."""
        with patch(
            "gh_link_auditor.policy_checker._fetch_raw_url",
            return_value=None,
        ):
            result = check_repository_policy("https://github.com/org/repo")
        assert result["is_blocked"] is False
        assert result["status"] == PolicyStatus.UNKNOWN
        assert result["contributing_found"] is False
