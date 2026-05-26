"""Lazy-import shim for AssemblyZero's PAT context manager — campaign-scoped.

The campaign-scoped classic PAT is used for two operations the fine-grained
PAT cannot perform: forking arbitrary public repos and opening cross-fork
PRs (see issue #185). It is least-privilege by design: ``public_repo`` scope
only, no admin or workflow rights (see LLD-397-398, issue #397).

The encrypted PAT lives at ``~/.secrets/link-auditor-pat.gpg`` and is
decrypted in-process by ``AssemblyZero/tools/_pat_session.py`` (ADR-0216).
This module does NOT import from AssemblyZero at module-load time. The
sys.path manipulation and underlying import are deferred until the
``link_auditor_pat_session()`` function is actually called. This way:

- ``from gh_link_auditor.classic_pat import link_auditor_pat_session`` is
  safe to do anywhere (including CI where AssemblyZero isn't installed).
- The error message is clear if a caller invokes it without AssemblyZero
  present.

Historical note: this module previously exported ``classic_pat_session``
(admin-scope). That function was removed in #397/#398 because nothing in
``src/`` consumed it — n6_submit_pr now uses the least-privilege shim
below. The ``tools/`` scripts (``add_test_workflow.py``,
``file_python_guide_numpy_pr.py``) import AssemblyZero's
``_pat_session.classic_pat_session`` directly; they need elevated scope
for their one-shot operations and are out of scope for this module.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

ASSEMBLYZERO_TOOLS = Path.home() / "Projects" / "AssemblyZero" / "tools"
LINK_AUDITOR_PAT_PATH = Path.home() / ".secrets" / "link-auditor-pat.gpg"


@contextmanager
def link_auditor_pat_session() -> Iterator[str]:
    """Yield the decrypted campaign-scoped PAT for the with-block duration.

    The PAT has ``public_repo`` scope only — enough to fork public repos
    and open cross-fork PRs, nothing else. A leak's blast radius is
    bounded to "spam PRs on public repos," not the admin-scope catastrophe
    a leaked classic PAT would cause across the fleet.

    Raises:
        RuntimeError: If the AssemblyZero tools directory cannot be found.
        FileNotFoundError: From the underlying _pat_session if the encrypted
            PAT file is missing. The error message includes the gpg-encrypt
            one-time setup command per ADR-0216 surface checklist.
        Other exceptions: From the underlying _pat_session if gpg fails
            (timeout, max-retry exceeded, etc.).
    """
    if not ASSEMBLYZERO_TOOLS.exists():
        raise RuntimeError(
            f"Campaign PAT requires AssemblyZero at {ASSEMBLYZERO_TOOLS}. "
            f"See LLD-397-398 and AssemblyZero ADR-0216 / issue #1344 for "
            f"the least-privilege PAT pattern."
        )
    if str(ASSEMBLYZERO_TOOLS) not in sys.path:
        sys.path.insert(0, str(ASSEMBLYZERO_TOOLS))

    from _pat_session import classic_pat_session as _real_session  # noqa: E402

    with _real_session(pat_path=LINK_AUDITOR_PAT_PATH) as pat:
        yield pat
