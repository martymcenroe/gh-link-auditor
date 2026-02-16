# Mr. Slant — The Link Judge

> Mr. Slant has been dead for several hundred years, which has not affected his legal practice in the slightest. He is meticulous, thorough, and his verdicts are beyond reproach — because he has all the time in the world.

## The Problem

Cheery (the Detective) finds candidate replacement URLs for dead links. But how confident are we that the replacement is correct? We need a judge to evaluate the evidence and render a verdict with a confidence score.

## The Judge's Process

Mr. Slant receives Cheery's forensic report and evaluates each candidate replacement:

### Confidence Scoring (0-100%)

| Signal | Weight | Description |
|--------|--------|-------------|
| HTTP redirect from dead URL to candidate | +40% | The server itself says "it moved here" |
| Title match (archived vs candidate) | +25% | Same or very similar page title |
| Content similarity (archived vs candidate) | +20% | Key phrases and structure match |
| URL path similarity | +10% | Similar path structure suggests same content |
| Domain match | +5% | Same domain = more trustworthy |

### Verdict Tiers

| Confidence | Verdict | Action |
|------------|---------|--------|
| >= 95% | **AUTO-APPROVE** | Replacement applied automatically |
| 75-94% | **HUMAN-REVIEW** | Escalate to HITL dashboard |
| 50-74% | **LOW-CONFIDENCE** | Flag for manual investigation |
| < 50% | **INSUFFICIENT** | No replacement — mark as "needs manual fix" |

## HITL Dashboard (Human Review)

When confidence is between 50-94%, the human needs to compare the old and new pages. Mr. Slant presents the evidence:

### Side-by-Side Review Interface

A lightweight HTML dashboard served locally (or as a static page) with:

- **Left pane:** Internet Archive snapshot of the dead URL (iframe)
- **Right pane:** Candidate replacement URL (iframe)
- **Header bar:** Dead URL, candidate URL, confidence score, investigation method
- **Action buttons:**
  - **Approve** — Accept this replacement
  - **Reject** — This is not the right page
  - **Abandon** — No replacement exists, remove the link
  - **Keep Looking** — Send back to Cheery for deeper investigation

### Technical Approach

- Simple Python HTTP server (`http.server`) serving a single HTML page
- Two iframes with independent scrolling
- WebSocket or polling for action submission back to the pipeline
- Keyboard shortcuts: `a` = approve, `r` = reject, `x` = abandon, `k` = keep looking
- Queue-based: presents one link at a time, advances on action

### Example Layout

```
+--------------------------------------------------+
| Dead: example.com/old  ->  example.com/new       |
| Confidence: 87% | Method: site_search             |
| [Approve] [Reject] [Abandon] [Keep Looking]       |
+------------------------+-------------------------+
|  Archive Snapshot      |  Candidate Page          |
|  (iframe, scrollable)  |  (iframe, scrollable)    |
|                        |                          |
|                        |                          |
+------------------------+-------------------------+
```

## Output

Mr. Slant produces a **verdict** for each dead link:

```json
{
  "dead_url": "https://example.com/old-page",
  "verdict": "HUMAN-REVIEW",
  "confidence": 87,
  "replacement_url": "https://example.com/new-page",
  "scoring_breakdown": {
    "redirect": 0,
    "title_match": 25,
    "content_similarity": 18,
    "url_similarity": 9,
    "domain_match": 5
  },
  "human_decision": null,
  "decided_at": null
}
```

After human review, `human_decision` is set to `approved`, `rejected`, `abandoned`, or `keep_looking`.

## Character Philosophy

Mr. Slant does not rush to judgment. He weighs every piece of evidence, assigns precise scores, and presents his verdict with full transparency. His confidence scores are not feelings — they are calculations. And when the evidence is insufficient, he says so rather than guessing.

Labels: feat, judge, link-resolution, hitl
