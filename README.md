# 📡 Expiry Radar

> *Everything in a codebase has a hidden expiration date. We find it before production does.*

IBM Bob 2.0 Hackathon - **Expiry Radar** scans a codebase for end-of-life dependencies, deprecated Qiskit APIs, stale workarounds for closed GitHub issues, and hardcoded expiry dates - then ranks them by urgency and auto-fixes the highest-severity ones with a single click.

---

## Live Demo

**Streamlit Cloud app:** https://rishma1999-expiry-radar-app.streamlit.app/

**GitHub repository:** [github.com/rishma1999/expiry-radar](https://github.com/rishma1999/expiry-radar)

### Run the agentic pipeline (terminal view)

```bash
bash demo_run.sh
```

Watch all 5 subagents fire in sequence:

| Agent | What it does | Output |
|---|---|---|
| 🤖 **EOL Collector** | Reads `requirements.txt`, queries `endoflife.date` API + IBM/Qiskit fallback map | `eol_findings.json` |
| 🤖 **Date & TODO Scanner** | Scans `.py`/`.md` for ISO dates and comment-anchored TODOs | `candidates.json` |
| 🤖 **GitHub Issues Agent** | Finds GitHub issue URLs, checks state via REST API, flags closed issues with live workarounds | `issue_findings.json` |
| 🤖 **Release Notes RAG** | Fetches 15 latest Qiskit releases, parses `Deprecated`/`Removed` sections, matches against codebase | `deprecation_findings.json` |
| 🤖 **Urgency Scorer** | Merges all sources, scores by `(1/days_left) × severity × confidence`, ranks all findings | `scored_findings.json` |

At the end the script prints the top 3 most urgent findings.
