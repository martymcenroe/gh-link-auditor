---
repo: martymcenroe/gh-link-auditor
issue: 19
url: https://github.com/martymcenroe/gh-link-auditor/issues/19
fetched: 2026-02-17T01:41:38.967552Z
---

# Issue #19: feat: Architect and Build Automated Link Checking Pipeline

### Context
We are building a robust, scalable link checking pipeline. This workflow integrates Dynamic Policy Adherence to format commit messages based on the target repository's standards.

### Phase 1: Core Infrastructure Setup (CLI & Python)
The initial focus is establishing the project repository (`link-check-pipeline`) and building the foundational Python tools.
* **Initialize Project:** Create the repository and set up the Poetry environment.
* **Core Link Checker (`link_checker.py`):** Build a script using Python (e.g., `requests`, `multiprocessing`) capable of recursively finding and validating links within a cloned repository path.
* **Tooling Integration:** Integrate and configure pipx tools like linters and formatters.

### Phase 2: Dynamic Policy Adherence & Repository Discovery
This phase introduces the intelligence layer that ensures compliance with external contribution standards.
* **Target Repository List:** Define a clean source to pull thousands of target repository URLs.
* **Policy_Discovery Function:** Build a function that fetches `CONTRIBUTING.md`, parses it for Commit Prefix/Scope and Closure Keywords, and stores results.
* **Authentication Setup:** Configure a high-rate GitHub token.

### Phase 3: Scalable Execution and PR Generation
* **Iteration Engine:** Iterate over the target list.
* **Per-Repository Workflow:** Fork & Clone, Execute Link Check, Apply Fixes.
* **Policy-Adherent Commit:** Use the standards retrieved in Phase 2 to formulate the professional commit message.
* **Submit PR:** Use `gh pr create --fill` to non-interactively submit the fix.

### Phase 4: Monitoring and Metrics
* **Tracking Database:** Implement a local database (SQLite) to log PR status.
* **Metrics Reporting:** Build a tool to generate metrics (acceptance rate, time-to-merge).
* **Maintenance:** Routine cleanup of local forks/branches.