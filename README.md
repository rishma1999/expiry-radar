# 📡 Expiry Radar

> *Everything in a codebase has a hidden expiration date. We find it before production does.*

IBM Bob 2.0 Hackathon — **Expiry Radar** scans a codebase for end-of-life dependencies, deprecated Qiskit APIs, stale workarounds for closed GitHub issues, and hardcoded expiry dates — then ranks them by urgency and auto-fixes the highest-severity ones with a single click.

---

## Live Demo

**Streamlit Cloud app:** _(deploy from [share.streamlit.io](https://share.streamlit.io) — repo: this repo, file: `app.py`)_

**GitHub repository:** [github.com/rishma1999/expiry-radar](https://github.com/rishma1999/expiry-radar)

---

## Demo Script — Step by Step

### 0 · One-time setup

```bash
# Clone and install
git clone https://github.com/rishma1999/expiry-radar.git
cd expiry-radar
pip install -r requirements.txt
```

Deploy to Streamlit Cloud:
1. Go to [share.streamlit.io](https://share.streamlit.io) → **New app**
2. Repository: `rishma1999/expiry-radar` · Branch: `main` · File: `app.py`
3. Copy the app URL (e.g. `https://expiry-radar.streamlit.app`)
4. Set it for the demo: `export STREAMLIT_URL=https://expiry-radar.streamlit.app`

---

### 1 · Reset to a fresh state

```bash
bash demo_reset.sh
```

What it does:
- ✅ Switches to `main` branch
- ✅ Deletes any leftover local fix branches
- ✅ Removes all generated `*.json` pipeline artifacts
- ✅ Resets `requirements.txt` to unpinned (so EOL findings appear live)
- ✅ Verifies all 5 collector scripts are present

---

### 2 · Run the agentic pipeline (terminal view)

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

At the end the script prints the top 3 most urgent findings and opens your Streamlit Cloud app.

---

### 3 · Walk through the Streamlit dashboard

Open your Streamlit Cloud URL. Click through the 6 tabs:

| Tab | What to show |
|---|---|
| **⏱ Timeline** | Urgency bars — red bars = critical, longer = closer to deadline |
| **📅 Calendar** | Findings grouped by the month they break |
| **📋 All Findings** | Sortable table, download as CSV |
| **🔍 Detail** | Click any finding: migration guidance, all file locations, raw JSON |
| **🔧 Auto-Fix** | ← _live demo here_ |
| **🧪 Backtest** | Precision/recall score against known Qiskit 0.7 breakages |

---

### 4 · Auto-Fix → Create PR (entirely in the browser)

In the **🔧 Auto-Fix** tab:

**Step 1 — Triage**  
The app classifies every finding: auto-fixable in this repo vs upstream Qiskit.

**Step 2 — Apply fixes**  
Click **✅ Apply fix** for:
- `EOL-001` → pins `cryptography>=44.0.0` (was EOL 2026-10-01)
- `EOL-002` → pins `pydantic>=2.0.0` (v1 was EOL 2024-06-30, 819 days past due)

**Step 3 — Upstream items**  
Each upstream Qiskit finding has a **↗ File upstream issue** button that opens GitHub's new-issue form pre-filled with the migration guidance.

**Step 4 — Create Pull Request**

Watch the progress checklist tick live:
```
✅ EOL-001 fixed         cryptography>=44.0.0 in requirements.txt
✅ EOL-002 fixed         pydantic>=2.0.0 in requirements.txt
⬜ Fix branch exists     fix/eol-pin-dependencies in local git
⬜ Branch ahead of main  0 commit(s) not yet in main
⬜ Branch pushed         github.com/rishma1999/expiry-radar/tree/fix/eol-pin-dependencies
```

Click **📦 Commit fixes & push branch** — watch the agentic commit trace panel:
```
🔧 Commit & Push Pipeline
✔ Stash any in-progress changes
✔ Create branch `fix/eol-pin-dependencies`
✔ Restore changes onto new branch
✔ Stage requirements.txt
✔ Commit with fix message
✔ Push to origin/fix/eol-pin-dependencies
```

Checklist turns fully green. Click **🚀 Open Pull Request on GitHub →**

GitHub opens with **branch, title, and PR body already filled in**. Click **Create pull request**.

---

### 5 · Review the PR on GitHub

The PR shows:
- Files changed: `requirements.txt` (2 lines pinned)
- Auto-generated description referencing EOL-001, EOL-002, evidence sources, test results
- No CLI, no OTP, no manual branch name typing

---

## Architecture

```
requirements.txt + codebase
        │
        ▼
  ┌─────────────────────────────────────────────────┐
  │  5 Python collectors (deterministic, no AI)      │
  │  collect_eol · collect_dates · collect_issues    │
  │  collect_release_notes · score                   │
  └──────────────────┬──────────────────────────────┘
                     │  scored_findings.json
                     ▼
           Streamlit Dashboard (app.py)
           Timeline · Calendar · Table
           Detail · Auto-Fix · Backtest
```

The collectors do cheap, deterministic scanning. The AI layer (Bob) does reasoning: changelog interpretation, migration guidance, fix generation. This is the IBM Bob design principle: *deterministic code for known processes, AI only for judgment*.

---

## Project structure

```
.
├── app.py                          # Streamlit dashboard (6 tabs)
├── requirements.txt                # Project dependencies
├── demo_reset.sh                   # Pre-demo reset script
├── demo_run.sh                     # Live demo pipeline runner
├── .streamlit/config.toml          # Streamlit Cloud theme config
└── .bob/
    └── skills/expiry-radar/
        ├── SKILL.md                # Bob skill definition
        ├── finding-schema.json     # Schema every finding must match
        ├── severity-guide.md       # Severity rules
        └── scripts/
            ├── collect_eol.py          # EOL Collector
            ├── collect_dates.py        # Date & TODO Scanner
            ├── collect_issues.py       # GitHub Issues Agent
            ├── collect_release_notes.py # Release Notes RAG
            ├── score.py                # Urgency Scorer
            └── backtest.py             # Backtest runner
```

---

## Security

- `.gitignore` and `.bobignore` block all credential file patterns (IBM Cloud API keys, `.env`, `*.pem`, `*.key`, GitHub tokens)
- Pipeline output JSONs (`*_findings.json`, `scored_findings.json`) are gitignored — they contain local file paths and are regenerated on each run
- No secrets are hardcoded anywhere in the codebase

