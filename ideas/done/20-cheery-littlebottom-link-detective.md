# Cheery Littlebottom — The Link Detective

> "The thing about forensic evidence is that it doesn't lie. It just sits there until someone smart enough comes along to read it." — paraphrasing the spirit of Cheery

## The Problem

When a link is dead (404, 410, DNS failure), we don't just want to report it — we want to **find where it went**. Pages move, domains change, projects restructure. The old content usually still exists somewhere.

## The Detective's Toolkit

Cheery has several investigative methods, tried in order:

### 1. The Wayback Machine (Internet Archive)
- Query `https://web.archive.org/web/*/URL` for the dead link
- Fetch the most recent archived snapshot
- Extract the page title and key content from the archived version
- This tells us **what the page used to contain** — the ground truth for matching

### 2. Site Crawl / Redirect Detection
- Follow any redirect chains from the dead URL (301, 302, 307, 308)
- Check common URL mutations: `/docs/` vs `/documentation/`, `/v1/` vs `/v2/`, trailing slashes
- Check if the domain itself redirected (e.g., `old-project.io` → `new-project.dev`)

### 3. Search Engine Query
- Take the archived page title and search `site:domain.com "page title"`
- If the domain is dead, search the title more broadly
- Look for the closest match by content similarity

### 4. Repository Heuristics (GitHub-specific)
- If the dead link is a GitHub URL, check if the repo was renamed, transferred, or archived
- GitHub API: `/repos/{owner}/{repo}` returns `301` with the new location on rename
- Check if the file was moved within the repo via `git log --follow`

## Output

For each dead link, Cheery produces a **forensic report**:

```json
{
  "dead_url": "https://example.com/old-page",
  "investigation": {
    "archive_snapshot": "https://web.archive.org/web/20240101/...",
    "archive_title": "The Original Page Title",
    "archive_content_summary": "First 500 chars of archived content",
    "candidate_replacements": [
      {
        "url": "https://example.com/new-page",
        "method": "redirect_chain",
        "similarity_score": 0.95
      },
      {
        "url": "https://example.com/docs/moved-page",
        "method": "site_search",
        "similarity_score": 0.82
      }
    ],
    "investigation_log": ["Step 1: Archive found...", "Step 2: No redirect..."]
  }
}
```

## Integration

- Cheery is called by the scanner after a dead link is confirmed
- She passes her forensic report to Mr. Slant (the Judge) for confidence evaluation
- If no candidates are found, the report says so — Cheery doesn't fabricate evidence

## Technical Approach

- Python stdlib + `urllib` for archive lookups (stay dependency-light)
- Optional: `beautifulsoup4` for HTML parsing of archived pages
- Internet Archive CDX API for precise snapshot queries
- Rate limiting per the backoff algorithm (00007)
- Results cached in the state database (#5) to avoid re-investigating known dead links

## Character Philosophy

Cheery Littlebottom doesn't jump to conclusions. She collects evidence, documents her process, and presents findings for others to judge. She's methodical, thorough, and occasionally discovers things nobody expected.

Labels: feat, detective, link-resolution
