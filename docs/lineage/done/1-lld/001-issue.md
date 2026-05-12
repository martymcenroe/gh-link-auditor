---
repo: martymcenroe/gh-link-auditor
issue: 1
url: https://github.com/martymcenroe/gh-link-auditor/issues/1
fetched: 2026-02-17T01:41:37.622534Z
---

# Issue #1: feat(script): Enhance check_links.py to handle anti-bot errors

The check_links.py script currently uses HTTP 'HEAD' requests for speed. \n\nHowever, many servers (e.g., go.dev, LinkedIn) block 'HEAD' requests with a 405 (Method Not Allowed) or 403 (Forbidden) error to prevent bot scraping.\n\nThis enhancement will modify the script:\n1.  Attempt the 'HEAD' request first.\n2.  If it fails with a 405 or 403 error, the script should automatically fall back and retry with a full 'GET' request to validate the link.\n