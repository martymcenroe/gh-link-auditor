"""Static host blocklist for Stage 3 investigation (#258).

Hosts in this set are skipped at the investigation stage — we record the
finding row as ``investigation_state='skipped_blocklist'`` and move on
without running LinkDetective against the URL. Saves wall time and reduces
operator-triage noise.

Two classes of hosts here:

1. **Anti-bot walls where humans get through.** Findings are NOT removal-PR
   candidates — the URLs work for real users. We just can't verify them
   from automation. Examples: huggingface.co, medium.com, openai.com.

2. **Walls that block humans too** (cert-broken, login-required without
   public access, etc.). Findings ARE removal-PR candidates. The blocklist
   still skips them at Stage 3 because LinkDetective can't help; the
   findings remain in the DB for the removal-PR-derivation pass.

The operator-investigation column from manual checks (browser-verified)
should be cross-referenced when building the removal-PR queue.

Conservative initial seed — only hosts with very high confidence in the
anti-bot or rebrand classification. Expand via #258's derive workflow as
ground-truth accumulates.
"""

from __future__ import annotations

from urllib.parse import urlparse

# Hosts where humans get through but our pipeline cannot — findings on these
# hosts are NOT removal-PR candidates.
ANTI_BOT_HUMANS_OK: frozenset[str] = frozenset(
    {
        "huggingface.co",
        "medium.com",
        "openai.com",
        "experimentalhistory.substack.com",
        "dl.acm.org",
        "ecode360.com",
        "kalshi.com",  # login wall (browser-verified 2026-05-23)
        "www.npmjs.com",
        "forums.welltrainedmind.com",
        "www.linkedin.com",  # 999 status signature
        "notes.andymatuschak.org",
        "glyphwiki.org",
        "gseth.com",
        "web.archive.org",  # findings ARE archive URLs; no replacement possible
    }
)

# Hosts where both humans and our pipeline are blocked — findings ARE
# removal-PR candidates (operator can file PRs to remove these references).
# Listed here so Stage 3 skips re-investigation; the removal-PR derivation
# pass uses these findings as input.
PIPELINE_AND_HUMANS_BLOCKED: frozenset[str] = frozenset(
    {
        "opendap.4tu.nl",  # cert broken (browser-verified 2026-05-23)
        "play.picoctf.org",  # rebranded to learn.cylabacademy.org (operator-verified)
    }
)

# Union of all blocklisted hosts. Stage 3 consults this set.
BLOCKLIST: frozenset[str] = ANTI_BOT_HUMANS_OK | PIPELINE_AND_HUMANS_BLOCKED


def is_blocklisted_host(url: str) -> bool:
    """True if the URL's host is in the static blocklist.

    Stage 1 inventory can also use this to drop URLs at extraction time
    once that integration ships (#258 Phase 2). For now, only Stage 3
    consults this — Stage 1 inventory is unchanged.
    """
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return False
    return host in BLOCKLIST
