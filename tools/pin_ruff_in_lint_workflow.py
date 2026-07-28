#!/usr/bin/env python3
"""Pin ruff's version in `.github/workflows/lint.yml` via the Contents API (#428).

`lint.yml` installs ruff with a bare `pip install ruff` — latest on every run.
ruff 0.16.0 began formatting Python code blocks inside markdown, which turned
main red on 2026-07-25 with zero repo changes (#423). This script pins the
install so a future ruff release cannot redden main the same way.

The fine-grained PAT used for normal git operations **cannot** create or update
workflow files (no `workflow` scope — that omission is load-bearing, see
ADR-0216 §1). The classic PAT can. Per ADR-0216 the classic PAT lives only in
this Python process's heap, decrypted via gpg.

**SCOPE NOTE.** This uses the FLEET classic PAT at ``~/.secrets/classic-pat.gpg``
(elevated), NOT the campaign PAT at ``~/.secrets/link-auditor-classic-pat.gpg``.
The campaign PAT is deliberately `public_repo`-only with no workflow rights
(#397/#398), so it cannot land this change. Same split as the existing
`tools/add_test_workflow.py`.

**THE USER RUNS THIS, NOT THE AGENT.** Per ADR-0216 gotcha #1: an agent
invoking this via its Bash tool would make the Python process the agent's
child, with theoretical heap-read access while the PAT is live. From your own
Git Bash, in the repo root:

    poetry run python tools/pin_ruff_in_lint_workflow.py

Self-contained and idempotent: it reads the current `lint.yml` from origin,
applies the substitution in memory, and exits early as a no-op if the pin is
already present. Nothing is read from or written to your working tree, so it
never leaves the tree dirty and does not care which branch you have checked
out. It creates the branch, commits, and opens the PR.
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

import httpx

# Import _pat_session from the AssemblyZero tools directory.
ASSEMBLYZERO_TOOLS = Path.home() / "Projects" / "AssemblyZero" / "tools"
if not ASSEMBLYZERO_TOOLS.exists():
    raise RuntimeError(f"Cannot find AssemblyZero tools at {ASSEMBLYZERO_TOOLS}")
sys.path.insert(0, str(ASSEMBLYZERO_TOOLS))
from _pat_session import classic_pat_session  # noqa: E402

REPO = "martymcenroe/gh-link-auditor"
BASE_BRANCH = "main"
# Distinct from the branch that carries this script (428-pin-ruff-ci) — the
# script must create a fresh branch for the workflow edit, not commit onto
# its own PR branch.
BRANCH = "428-pin-ruff-lint-yml"
WORKFLOW_PATH = ".github/workflows/lint.yml"

RUFF_VERSION = "0.16.0"
OLD_INSTALL = "pip install ruff"
NEW_INSTALL = f"pip install ruff=={RUFF_VERSION}"

COMMIT_MESSAGE = f"ci: pin ruff=={RUFF_VERSION} in lint workflow\n\nCloses #428"
PR_TITLE = f"ci: pin ruff=={RUFF_VERSION} in lint workflow (Closes #428)"
PR_BODY = f"""## Problem

`lint.yml` installed ruff with a bare `pip install ruff` — latest on every run.
ruff {RUFF_VERSION} began formatting Python code blocks inside markdown, which turned
main red on 2026-07-25 with no repo change behind it (#423, fixed by the
106-file reformat in #430). Any future ruff release can do this again.

## What

Pin the CI install to `ruff=={RUFF_VERSION}` — the version that formatted the tree in
#430 and the version now locked as a dev dependency (#429). Bump the two
together, deliberately, alongside any reformat commit.

Landed via the ADR-0216 classic-PAT Contents API path (`tools/pin_ruff_in_lint_workflow.py`),
operator-run: the fine-grained PAT cannot push workflow files.

Closes #428
"""

GH_API = "https://api.github.com"
HTTP_TIMEOUT_S = 30


def _get_file(client: httpx.Client, ref: str) -> tuple[str, str]:
    """Return (decoded_text, sha) for WORKFLOW_PATH at ref."""
    r = client.get(f"{GH_API}/repos/{REPO}/contents/{WORKFLOW_PATH}", params={"ref": ref})
    r.raise_for_status()
    payload = r.json()
    text = base64.b64decode(payload["content"]).decode("utf-8")
    return text, payload["sha"]


def _branch_exists(client: httpx.Client) -> bool:
    r = client.get(f"{GH_API}/repos/{REPO}/git/ref/heads/{BRANCH}")
    if r.status_code == 404:
        return False
    r.raise_for_status()
    return True


def _create_branch(client: httpx.Client) -> None:
    r = client.get(f"{GH_API}/repos/{REPO}/git/ref/heads/{BASE_BRANCH}")
    r.raise_for_status()
    base_sha = r.json()["object"]["sha"]
    r = client.post(
        f"{GH_API}/repos/{REPO}/git/refs",
        json={"ref": f"refs/heads/{BRANCH}", "sha": base_sha},
    )
    r.raise_for_status()
    print(f"  branch {BRANCH} created from {BASE_BRANCH}@{base_sha[:8]}")


def _put_file(client: httpx.Client, text: str, sha: str) -> None:
    # Content is assembled in memory from origin's bytes, so there is no CRLF
    # to normalize (ADR-0216 gotcha #3 applies to reads off a Windows tree).
    payload = {
        "message": COMMIT_MESSAGE,
        "content": base64.b64encode(text.encode("utf-8")).decode("ascii"),
        "branch": BRANCH,
        "sha": sha,
    }
    r = client.put(f"{GH_API}/repos/{REPO}/contents/{WORKFLOW_PATH}", json=payload)
    r.raise_for_status()
    print(f"  → {r.json()['commit']['sha'][:8]} committed to {BRANCH}")


def _open_pr(client: httpx.Client) -> None:
    r = client.post(
        f"{GH_API}/repos/{REPO}/pulls",
        json={"title": PR_TITLE, "body": PR_BODY, "head": BRANCH, "base": BASE_BRANCH},
    )
    if r.status_code == 422 and "already exists" in r.text:
        print("  PR already open for this branch")
        return
    r.raise_for_status()
    print(f"  PR opened: {r.json()['html_url']}")


def main() -> int:
    print(f"Pinning ruff=={RUFF_VERSION} in {REPO}:{WORKFLOW_PATH}")

    with classic_pat_session() as pat:
        client = httpx.Client(
            headers={
                "Authorization": f"Bearer {pat}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=HTTP_TIMEOUT_S,
        )
        with client:
            text, _ = _get_file(client, BASE_BRANCH)

            if NEW_INSTALL in text:
                print(f"  already pinned to {RUFF_VERSION} on {BASE_BRANCH} — nothing to do")
                return 0
            if OLD_INSTALL not in text:
                print(
                    f"ERROR: neither {OLD_INSTALL!r} nor {NEW_INSTALL!r} found in "
                    f"{WORKFLOW_PATH}. The workflow changed shape; re-read it and "
                    f"update this script rather than guessing.",
                    file=sys.stderr,
                )
                return 1

            # Substitute only the exact install line; `ruff check` / `ruff format`
            # invocations elsewhere in the file must not be touched.
            new_text = text.replace(f"run: {OLD_INSTALL}\n", f"run: {NEW_INSTALL}\n")
            if new_text == text:
                print(
                    f"ERROR: found {OLD_INSTALL!r} but not as a `run:` step; refusing to guess at the right edit.",
                    file=sys.stderr,
                )
                return 1

            if not _branch_exists(client):
                _create_branch(client)
            else:
                print(f"  branch {BRANCH} already exists — committing onto it")

            # Re-read at the branch tip for the correct blob SHA.
            _, branch_sha = _get_file(client, BRANCH)
            _put_file(client, new_text, branch_sha)
            _open_pr(client)

    print("Done. Wait for checks, then merge:")
    print(f"  gh pr merge --squash --repo {REPO} <PR#>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
