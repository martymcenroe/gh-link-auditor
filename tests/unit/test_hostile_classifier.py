"""Tests for the hostile-comment classifier helpers.

See LLD-178 for the classifier design and the conservative phrase list.
"""

from __future__ import annotations

from gh_link_auditor.hostile_classifier import (
    ANTI_AI_PHRASES,
    HOSTILE_PHRASES,
    MAINTAINER_ASSOCIATIONS,
    is_anti_ai_text,
    is_hostile_text,
    is_maintainer_comment,
)


class TestIsHostileText:
    """`is_hostile_text` returns True iff a hostile phrase appears."""

    def test_clean_text_is_not_hostile(self) -> None:
        assert is_hostile_text("Thanks for the PR! LGTM, merging now.") is False

    def test_empty_string_is_not_hostile(self) -> None:
        assert is_hostile_text("") is False

    def test_none_is_not_hostile(self) -> None:
        # type: ignore[arg-type] — explicit None safety check
        assert is_hostile_text(None) is False  # type: ignore[arg-type]

    def test_case_insensitive(self) -> None:
        assert is_hostile_text("FUCK OFF") is True
        assert is_hostile_text("Fuck Off") is True
        assert is_hostile_text("fuck off") is True

    def test_phrase_in_longer_body(self) -> None:
        body = "I do not want any more PRs. Stop opening PRs to this repo, thanks."
        assert is_hostile_text(body) is True

    def test_each_phrase_hits(self) -> None:
        for phrase in HOSTILE_PHRASES:
            assert is_hostile_text(phrase) is True, f"phrase missed: {phrase!r}"
            assert is_hostile_text(f"prefix {phrase} suffix") is True

    def test_partial_word_does_not_hit(self) -> None:
        # "spam" by itself isn't in the phrase list — only "spammer" is.
        assert is_hostile_text("This went to my spam folder, sorry for the late reply.") is False

    def test_unicode_body(self) -> None:
        assert is_hostile_text("merci! fuck off translates to —") is True


class TestIsMaintainerComment:
    """`is_maintainer_comment` accepts only OWNER/MEMBER/COLLABORATOR."""

    def test_owner_is_maintainer(self) -> None:
        assert is_maintainer_comment("OWNER") is True

    def test_member_is_maintainer(self) -> None:
        assert is_maintainer_comment("MEMBER") is True

    def test_collaborator_is_maintainer(self) -> None:
        assert is_maintainer_comment("COLLABORATOR") is True

    def test_contributor_is_not_maintainer(self) -> None:
        assert is_maintainer_comment("CONTRIBUTOR") is False

    def test_first_time_contributor_is_not_maintainer(self) -> None:
        assert is_maintainer_comment("FIRST_TIME_CONTRIBUTOR") is False

    def test_none_association_is_not_maintainer(self) -> None:
        assert is_maintainer_comment("NONE") is False

    def test_null_association_is_not_maintainer(self) -> None:
        assert is_maintainer_comment(None) is False

    def test_empty_string_is_not_maintainer(self) -> None:
        assert is_maintainer_comment("") is False

    def test_lowercase_normalized(self) -> None:
        assert is_maintainer_comment("owner") is True


class TestConstants:
    """The constant sets are conservative and stable shapes."""

    def test_maintainer_set_size(self) -> None:
        # OWNER, MEMBER, COLLABORATOR — anything else and the bias has shifted.
        assert MAINTAINER_ASSOCIATIONS == frozenset({"OWNER", "MEMBER", "COLLABORATOR"})

    def test_no_empty_phrases(self) -> None:
        assert all(p and p == p.lower() for p in HOSTILE_PHRASES)

    def test_no_empty_anti_ai_phrases(self) -> None:
        assert all(p and p == p.lower() for p in ANTI_AI_PHRASES)


class TestIsAntiAiText:
    """`is_anti_ai_text` returns True iff an anti-AI phrase appears (#200)."""

    def test_clean_text_is_not_anti_ai(self) -> None:
        assert is_anti_ai_text("Thanks for the PR! Merging.") is False

    def test_empty_string_is_not_anti_ai(self) -> None:
        assert is_anti_ai_text("") is False

    def test_none_is_not_anti_ai(self) -> None:
        assert is_anti_ai_text(None) is False

    def test_pallets_flask_rejection_text(self) -> None:
        """Real-world: davidism's pallets/flask #6019 comment hits."""
        body = "Happy to update this, but please do not use genAI to generate or submit a PR."
        assert is_anti_ai_text(body) is True

    def test_case_insensitive(self) -> None:
        assert is_anti_ai_text("NO AI-GENERATED PR PLEASE") is True

    def test_each_phrase_hits(self) -> None:
        for phrase in ANTI_AI_PHRASES:
            assert is_anti_ai_text(phrase) is True, f"phrase missed: {phrase!r}"
            assert is_anti_ai_text(f"prefix {phrase} suffix") is True

    def test_hostile_text_is_not_anti_ai(self) -> None:
        """Bias: anti-AI and hostile are disjoint signals."""
        assert is_anti_ai_text("fuck off") is False

    def test_anti_ai_text_is_not_hostile(self) -> None:
        """Bias: anti-AI text doesn't trigger the rude classifier."""
        assert is_hostile_text("please do not use AI to generate PRs") is False
