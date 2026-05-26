"""Tests for the gh_link_auditor.classic_pat shim module.

See LLD-397-398 and AssemblyZero#1344 for the design rationale.
"""

from __future__ import annotations

import sys
import types
from contextlib import contextmanager
from pathlib import Path

import pytest

from gh_link_auditor.classic_pat import (
    LINK_AUDITOR_PAT_PATH,
    link_auditor_pat_session,
)


def test_link_auditor_pat_path_is_in_secrets_dir() -> None:
    """The campaign PAT lives at ~/.secrets/link-auditor-pat.gpg.

    Operators following the one-time setup in LLD-397-398 §5 will
    gpg-encrypt to this exact path. Drift here breaks every submission.
    """
    assert LINK_AUDITOR_PAT_PATH == Path.home() / ".secrets" / "link-auditor-pat.gpg"


def test_link_auditor_pat_path_is_separate_from_admin_classic_pat() -> None:
    """#397: campaign PAT and admin PAT must NOT share a path.

    Reusing ~/.secrets/classic-pat.gpg would re-introduce the asymmetric
    blast radius the least-privilege design was created to avoid.
    """
    admin_classic_path = Path.home() / ".secrets" / "classic-pat.gpg"
    assert LINK_AUDITOR_PAT_PATH != admin_classic_path


def test_link_auditor_pat_session_is_callable() -> None:
    """The shim is importable and callable without entering its context."""
    assert callable(link_auditor_pat_session)


def test_link_auditor_pat_session_raises_when_assemblyzero_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Missing AssemblyZero → RuntimeError naming both LLD-397-398 and AZ#1344.

    Operators searching the chat for either reference should find the
    error message and reach the setup runbook.
    """
    from gh_link_auditor import classic_pat

    fake_missing = tmp_path / "definitely-not-here"
    monkeypatch.setattr(classic_pat, "ASSEMBLYZERO_TOOLS", fake_missing)

    with pytest.raises(RuntimeError, match="LLD-397-398"):
        with classic_pat.link_auditor_pat_session():
            pass


def test_link_auditor_pat_session_forwards_path_to_underlying_real_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The shim must call _pat_session.classic_pat_session(pat_path=LINK_AUDITOR_PAT_PATH).

    Passing the wrong path would silently decrypt the admin PAT,
    silently re-introducing the asymmetric blast radius #397 fixed.
    """
    from gh_link_auditor import classic_pat

    # Bypass the AssemblyZero existence gate without needing it installed.
    monkeypatch.setattr(classic_pat, "ASSEMBLYZERO_TOOLS", tmp_path)

    received_paths: list[Path | None] = []

    @contextmanager
    def fake_real_session(pat_path: Path | None = None):
        received_paths.append(pat_path)
        yield "ghp_fake_campaign_decrypted"

    fake_module = types.ModuleType("_pat_session")
    fake_module.classic_pat_session = fake_real_session  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "_pat_session", fake_module)

    with classic_pat.link_auditor_pat_session() as pat:
        assert pat == "ghp_fake_campaign_decrypted"

    assert received_paths == [LINK_AUDITOR_PAT_PATH], f"shim called underlying with wrong path: {received_paths}"
