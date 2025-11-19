# gh-link-auditor

**Enterprise-grade link auditor and repository graph expander with Human-in-the-Loop (HITL) resolution.**

This tool is designed for Power Engineers, Architects, and Maintainers who need to ensure the integrity of documentation across a vast network of repositories.

## 🚀 Features (Current & Planned)

* **Link Integrity Audit:** Validates HTTP/HTTPS links using `HEAD` requests with intelligent fallbacks to `GET` for anti-bot handling.
* **Graph Expansion:** (Planned) Discover related repositories via star-graphs and dependencies to build a comprehensive domain map.
* **Human-in-the-Loop (HITL):** (Planned) Interactive CLI mode to resolve 404/403 errors with LLM-assisted suggestions.
* **State Management:** (Planned) SQLite tracking of audit history to prevent repetitive scanning.

## 🛠️ Usage

```bash
# Run audit on the current directory's README
python check_links.py
```

## 🤝 Sponsorship

If this tool saves you time, please consider [sponsoring the development](https://github.com/sponsors/martymcenroe).