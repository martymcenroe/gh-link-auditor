

ORCHESTRATOR CLARIFICATION NEEDED:

**Conflict between Gemini Review #2 and Gemini Review #3 regarding scope splitting:**

1. **Gemini Review #2** says to split into **two** issues:
   - Core Pipeline (N0–N7 wiring + CLI `run` command)
   - Campaign Dashboard (`dashboard` command, HTML templates, DB aggregation)

2. **Gemini Review #3** says to split into **three** issues:
   - Pipeline Core (N0–N5)
   - PR Automation (N6)
   - Campaign Dashboard (N7)

3. **The current draft's Implementation Phases table** already defines a 3-phase split (Core N0–N3+N5, PR Automation N6, Dashboard N7) but the Acceptance Criteria cover all phases — which Review #3 flags as a "scope contradiction."

**Questions:**

- Should I scope this issue to **Phase 1 only** (Pipeline Core: N0–N5 + cost circuit breaker) and remove ACs for N6/N7/dashboard, matching the 3-phase split from Review #3?
- Or should I scope it as the **2-issue split** from Review #2 (all pipeline nodes N0–N7 in this issue, dashboard as separate)?
- Or should this remain a single epic-sized issue with all ACs, and I just remove the contradictory Implementation Phases table?

**Additionally, Gemini Review #3 Tier 1 Cost blocking issue:**

- Review #3 requires specifying the **model class** (e.g., GPT-4o, Claude Sonnet, local model) for Mr. Slant LLM calls. The current draft says "Mr. Slant (LLM calls)" without specifying. What model should I specify, or should I say "configurable via environment variable, defaults to [X]"?

**Also, Gemini Review #3 Tier 1 Legal blocking issue:**

- Review #3 requires an explicit statement that **"Data processing is Local-Only"** to satisfy Privacy & Data Residency. Should I add this as a standalone statement in Security Considerations, or as a new "Data Residency" subsection?