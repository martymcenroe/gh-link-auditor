---
repo: martymcenroe/gh-link-auditor
issue: 4
url: https://github.com/martymcenroe/gh-link-auditor/issues/4
fetched: 2026-02-17T01:39:53.836384Z
---

# Issue #4: feat(bot): Add 'Maintainer Policy Check' module

To ensure the 'Doc-Fix Bot' is a 'good citizen' and not a 'spammer', we must check repository contribution policies.\n\n**Acceptance Criteria:**\n1.  Before scanning a repo, the bot must check for a  file.\n2.  It will parse this file for specific keywords (e.g., 'no-bot', 'no-pr', 'typos-welcome', 'skip-doc-prs', 'contact-first').\n3.  If a 'do-not-disturb' keyword is found, the bot will automatically skip the repo and log it in the state database as 'policy-blacklisted'.