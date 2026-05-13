"""Lazy-import shim for AssemblyZero's classic-PAT context manager.

The classic PAT is required for two operations the fine-grained PAT cannot
perform: forking arbitrary public repos and opening cross-fork PRs (see
issue #185). The PAT itself lives encrypted at ~/.secrets/classic-pat.gpg
and is decrypted in-process by ``AssemblyZero/tools/_pat_session.py``
(ADR-0216).

This module does NOT import from AssemblyZero at module-load time. The
sys.path manipulation and underlying import are deferred until the
``classic_pat_session()`` function is actually called. This way:

- ``from gh_link_auditor.classic_pat import classic_pat_session`` is safe
  to do anywhere (including CI where AssemblyZero isn't installed).
- The error message is clear if a caller invokes it without AssemblyZero
  present.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

ASSEMBLYZERO_TOOLS = Path.home() / "Projects" / "AssemblyZero" / "tools"


@contextmanager
def classic_pat_session() -> Iterator[str]:
    """Yield the decrypted classic PAT for the duration of the with-block.

    Raises:
        RuntimeError: If the AssemblyZero tools directory cannot be found.
        FileNotFoundError: From the underlying _pat_session if the encrypted
            PAT file is missing.
        Other exceptions: From the underlying _pat_session if gpg fails.
    """
    if not ASSEMBLYZERO_TOOLS.exists():
        raise RuntimeError(
            f"Classic PAT requires AssemblyZero at {ASSEMBLYZERO_TOOLS}. "
            f"This pipeline node needs the elevated-scope token for forking "
            f"external repos and opening cross-fork PRs (see issue #185)."
        )
    if str(ASSEMBLYZERO_TOOLS) not in sys.path:
        sys.path.insert(0, str(ASSEMBLYZERO_TOOLS))

    from _pat_session import classic_pat_session as _real_session  # noqa: E402

    with _real_session() as pat:
        yield pat
