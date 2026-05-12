---
repo: martymcenroe/gh-link-auditor
issue: 3
url: https://github.com/martymcenroe/gh-link-auditor/issues/3
fetched: 2026-02-17T01:39:52.684465Z
---

# Issue #3: feat: Architect 'Repo Scout' for organic target discovery

Building on the 'Doc-Fix Bot', this project is a 'scout' to find new repositories. \n\n**Components:**\n1.  **Awesome List Parser:** Ingests a list of 'Awesome' repositories and parses all GitHub links.\n2.  **Star-Walker:** Given a root user (e.g., 'martymcenroe'), scans all their starred repos and (optionally) the starred repos of their connections.\n3.  **LLM Brainstormer:** Uses an LLM API to suggest new, relevant repos based on keywords (e.g., 'AI', 'Power Systems').\n\n**Goal:** The output will be a massive, de-duplicated  file for the 'Doc-Fix Bot' to consume.