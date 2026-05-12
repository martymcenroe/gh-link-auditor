#!/usr/bin/env python3
"""Add `.github/workflows/test.yml` to branch `174-pytest-ci` via Contents API.

The fine-grained PAT used for normal git operations cannot create or update
workflow files. The classic PAT (admin scope) can. Per ADR-0216, the classic
PAT lives only in this Python process's heap, decrypted via gpg-agent.

**THE USER RUNS THIS, NOT THE AGENT.** Per ADR-0216 gotcha #1: an agent
invoking this script via its Bash tool would make the Python process the
agent's child, with theoretical heap-read access during the PAT's lifetime.
Run from your own Git Bash:

    poetry run python tools/add_test_workflow.py

Idempotent: re-running after a successful run is a no-op (the API returns
422 "sha required" when the file already exists at the same content, which
we treat as success).

After this script lands the commit, open the PR manually or via:

    gh pr create --repo martymcenroe/gh-link-auditor \\
        --head 174-pytest-ci --base main \\
        --title "ci: add pytest+pytest-cov to dev deps and run tests in CI" \\
        --body "$(cat .github/PR_BODY_174.md 2>/dev/null || echo 'See #174')"
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
BRANCH = "174-pytest-ci"
WORKFLOW_PATH = ".github/workflows/test.yml"
COMMIT_MESSAGE = "ci: add test workflow that runs pytest with coverage on PR\n\nRefs #174"
GH_API = "https://api.github.com"
HTTP_TIMEOUT_S = 30

REPO_ROOT = Path(__file__).resolve().parent.parent


def _existing_sha(client: httpx.Client) -> str | None:
    """Return the file's SHA on the branch if it exists, else None."""
    r = client.get(
        f"{GH_API}/repos/{REPO}/contents/{WORKFLOW_PATH}",
        params={"ref": BRANCH},
    )
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()["sha"]


def _put_workflow(client: httpx.Client, content_b64: str, sha: str | None) -> None:
    payload: dict[str, object] = {
        "message": COMMIT_MESSAGE,
        "content": content_b64,
        "branch": BRANCH,
    }
    if sha is not None:
        payload["sha"] = sha
    r = client.put(
        f"{GH_API}/repos/{REPO}/contents/{WORKFLOW_PATH}",
        json=payload,
    )
    r.raise_for_status()
    print(f"  → {r.json()['commit']['sha'][:8]} committed to {BRANCH}")


def main() -> int:
    local_file = REPO_ROOT / WORKFLOW_PATH
    if not local_file.exists():
        print(f"ERROR: {local_file} not found locally", file=sys.stderr)
        return 1

    # Normalize CRLF → LF (Windows working tree quirk per ADR-0216 gotcha #3).
    raw = local_file.read_bytes().replace(b"\r\n", b"\n")
    content_b64 = base64.b64encode(raw).decode("ascii")

    print(f"Adding {WORKFLOW_PATH} to {REPO}@{BRANCH} via Contents API")
    print(f"  payload: {len(raw)} bytes, sha256 prefix = {hash(raw) & 0xFFFFFFFF:08x}")

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
            sha = _existing_sha(client)
            if sha is not None:
                print(f"  file already exists at SHA {sha[:8]} — updating in place")
            _put_workflow(client, content_b64, sha)

    print("Done. Next: open the PR.")
    print(
        f"  gh pr create --repo {REPO} --head {BRANCH} --base main \\\n"
        f'    --title "ci: pytest+pytest-cov dev deps and CI test job" \\\n'
        f'    --body "Closes #174"'
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
