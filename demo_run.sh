#!/usr/bin/env bash
# =============================================================================
# demo_run.sh - Expiry Radar · Live demo pipeline runner
# =============================================================================
# Runs all 5 agents in sequence with visible output, then opens the
# Streamlit Cloud app in the browser - no localhost ever started.
#
# Prerequisites:
#   1. Run `bash demo_reset.sh` first (cleans artifacts + resets requirements.txt)
#   2. The app must already be deployed to Streamlit Cloud.
#      Set STREAMLIT_URL below, or export it before running this script:
#        export STREAMLIT_URL="https://your-app-name.streamlit.app"
#
# Usage:
#   bash demo_run.sh
#   STREAMLIT_URL=https://expiry-radar.streamlit.app bash demo_run.sh
# =============================================================================
set -euo pipefail

SCRIPTS=".bob/skills/expiry-radar/scripts"
PYTHON="python3"

# ── Streamlit Cloud URL ───────────────────────────────────────────────────────
# Set this once to your deployed app. Never a localhost URL.
STREAMLIT_URL="${STREAMLIT_URL:-}"

# Derive GitHub repo from git remote (no hardcoding)
REMOTE_URL=$(git remote get-url origin 2>/dev/null || echo "")
if [[ "$REMOTE_URL" =~ github\.com[:/](.+?)(\.git)?$ ]]; then
  GH_REPO="${BASH_REMATCH[1]}"
else
  GH_REPO="rishma1999/expiry-radar"
fi
GH_REPO_URL="https://github.com/${GH_REPO}"

# ── Colour helpers ────────────────────────────────────────────────────────────
BOLD=$'\033[1m'; RESET=$'\033[0m'
GREEN=$'\033[32m'; BLUE=$'\033[34m'; YELLOW=$'\033[33m'
CYAN=$'\033[36m'; DIM=$'\033[2m'; RED=$'\033[31m'

banner() { echo ""; echo "${BOLD}${BLUE}━━  $1  ${RESET}"; echo ""; }
step()   { echo "  ${CYAN}◉${RESET}  ${BOLD}$1${RESET}"; }
tick()   { echo "  ${GREEN}✔${RESET}  $1"; }
info()   { echo "  ${DIM}$1${RESET}"; }
pause()  { sleep "${1:-1}"; }

# =============================================================================
echo ""
echo "${BOLD}${CYAN}╔══════════════════════════════════════════════════════════════╗${RESET}"
echo "${BOLD}${CYAN}║   📡  Expiry Radar - IBM Bob 2.0 Hackathon Demo              ║${RESET}"
echo "${BOLD}${CYAN}║   'Everything has a hidden expiration date. We find it.'     ║${RESET}"
echo "${BOLD}${CYAN}╚══════════════════════════════════════════════════════════════╝${RESET}"
pause 2

# ── Guard: must be on main, must have clean artifacts ────────────────────────
CURRENT_BRANCH=$(git branch --show-current)
if [ "$CURRENT_BRANCH" != "main" ]; then
  echo "${YELLOW}⚠  Not on main (on '$CURRENT_BRANCH'). Run bash demo_reset.sh first.${RESET}"
  exit 1
fi
if [ -f "scored_findings.json" ]; then
  echo "${YELLOW}⚠  scored_findings.json already exists. Run bash demo_reset.sh first.${RESET}"
  exit 1
fi

# ── AGENT 1: EOL Collector ────────────────────────────────────────────────────
banner "🤖 Agent 1 / 5 - EOL Collector"
step  "Reads requirements.txt"
step  "Queries endoflife.date API + IBM/Qiskit hardcoded fallback map"
step  "Emits eol_candidates.json + eol_findings.json"
pause 1
$PYTHON "$SCRIPTS/collect_eol.py"
tick  "eol_findings.json written"
pause 1

# ── AGENT 2: Date & TODO Scanner ─────────────────────────────────────────────
banner "🤖 Agent 2 / 5 - Date & TODO Scanner"
step  "Scans all .py and .md files for hardcoded ISO dates"
step  "Matches only comment-anchored TODOs (filters author names + prose)"
step  "Emits candidates.json"
pause 1
$PYTHON "$SCRIPTS/collect_dates.py"
tick  "candidates.json written"
pause 1

# ── AGENT 3: GitHub Issues Agent ─────────────────────────────────────────────
banner "🤖 Agent 3 / 5 - GitHub Issues Agent"
step  "Scans codebase for GitHub issue URLs"
step  "Calls GitHub REST API - checks current state (open / closed)"
step  "Flags CLOSED issues where workaround comment is still in code"
step  "Emits issue_candidates.json + issue_findings.json"
pause 1
$PYTHON "$SCRIPTS/collect_issues.py"
tick  "issue_findings.json written"
pause 1

# ── AGENT 4: Release Notes RAG ───────────────────────────────────────────────
banner "🤖 Agent 4 / 5 - Release Notes RAG"
step  "Fetches 15 latest Qiskit GitHub releases"
step  "Parses Deprecated / Removed sections"
step  "Cross-references IBM/Qiskit deprecation catalog"
step  "Scans codebase for matches - emits deprecation_findings.json"
pause 1
$PYTHON "$SCRIPTS/collect_release_notes.py"
tick  "deprecation_findings.json written"
pause 1

# ── AGENT 5: Urgency Scorer ──────────────────────────────────────────────────
banner "🤖 Agent 5 / 5 - Urgency Scorer"
step  "Merges all 4 findings sources"
step  "Scores: urgency = (1/days_left) × severity_weight × confidence"
step  "Ranks + emits scored_findings.json"
pause 1
$PYTHON "$SCRIPTS/score.py"
tick  "scored_findings.json written"
pause 1

# ── Pipeline summary ──────────────────────────────────────────────────────────
echo ""
echo "${BOLD}${GREEN}══════════════════════════════════════════════════════════════${RESET}"
echo "${BOLD}${GREEN}  ✅  All 5 agents complete.${RESET}"
echo "${BOLD}${GREEN}══════════════════════════════════════════════════════════════${RESET}"

$PYTHON - << 'PYEOF'
import json

with open("scored_findings.json") as f:
    findings = json.load(f)

counts = {}
for fin in findings:
    s = fin.get("severity", "?")
    counts[s] = counts.get(s, 0) + 1

print(f"\n  📊  {len(findings)} findings ranked by urgency:")
for sev in ["critical", "high", "medium", "low"]:
    n = counts.get(sev, 0)
    bar = "█" * n
    print(f"       {sev:8s}  {bar}  ({n})")

print("\n  🏆  Top 3 most urgent:")
for fin in findings[:3]:
    dl = fin.get("days_left")
    dl_s = f"{dl}d" if dl is not None else "stale"
    print(f"       [{fin['rank']}] {fin['id']}  {fin['severity']:8s}  "
          f"score={fin['urgency_score']:.3f}  {fin['title'][:55]}")
print()
PYEOF

pause 2

# ── Open Streamlit Cloud app ──────────────────────────────────────────────────
echo ""
echo "${BOLD}${CYAN}━━  Next: Streamlit Dashboard  ━━${RESET}"
echo ""

if [ -n "$STREAMLIT_URL" ]; then
  echo "  Opening Streamlit Cloud app: ${BOLD}${STREAMLIT_URL}${RESET}"
  echo ""
  echo "  ${BOLD}Demo walkthrough (in the browser):${RESET}"
  echo "  ┌─────────────────────────────────────────────────────────┐"
  echo "  │  Tab 1  ⏱  Timeline   - urgency bars, red = critical    │"
  echo "  │  Tab 2  📅  Calendar   - breakages grouped by month     │"
  echo "  │  Tab 3  📋  All Findings - sortable table, CSV export   │"
  echo "  │  Tab 4  🔍  Detail     - migration guidance per finding │"
  echo "  │  Tab 5  🔧  Auto-Fix   - apply fixes → commit → PR      │"
  echo "  │  Tab 6  🧪  Backtest   - precision/recall vs qiskit     │"
  echo "  └─────────────────────────────────────────────────────────┘"
  echo ""
  echo "  ${BOLD}In the Auto-Fix tab:${RESET}"
  echo "  Step 1  - triage (auto-fixable vs upstream)"
  echo "  Step 2  - click ✅ Apply fix for EOL-001 and EOL-002"
  echo "  Step 3  - upstream items link to GitHub issue form"
  echo "  Step 4  - progress checklist ticks live; click"
  echo "            ${BOLD}📦 Commit fixes & push branch${RESET}"
  echo "            then ${BOLD}🚀 Open Pull Request on GitHub →${RESET}"
  echo ""

  # Open in default browser (cross-platform)
  if command -v open &>/dev/null; then
    open "$STREAMLIT_URL"
  elif command -v xdg-open &>/dev/null; then
    xdg-open "$STREAMLIT_URL"
  fi
  pause 1

  # Show GitHub PR compare URL (no hardcoded branch - will be filled by Step 4)
  echo "  ${DIM}After pushing from the app, GitHub will open at:${RESET}"
  echo "  ${BOLD}${GH_REPO_URL}/compare${RESET}"
  echo "  (The app pre-fills branch, title, and PR body automatically.)"

else
  echo "${YELLOW}⚠  STREAMLIT_URL is not set.${RESET}"
  echo ""
  echo "  To deploy to Streamlit Cloud (one-time setup):"
  echo "  1. Go to  ${BOLD}https://share.streamlit.io${RESET}"
  echo "  2. Click  ${BOLD}New app${RESET}"
  echo "  3. Repo:  ${BOLD}${GH_REPO_URL}${RESET}"
  echo "     Branch: main   |   Main file: app.py"
  echo "  4. Copy the app URL and set it in your environment:"
  echo "     ${BOLD}export STREAMLIT_URL=https://<your-app>.streamlit.app${RESET}"
  echo ""
  echo "  Then re-run:  ${BOLD}bash demo_run.sh${RESET}"
  echo ""
  echo "  ${DIM}(For a quick local preview only - not for demo recording:)${RESET}"
  echo "  ${DIM}streamlit run app.py --server.headless true${RESET}"
fi

echo ""
echo "${BOLD}${GREEN}  📡  Expiry Radar demo complete.${RESET}"
echo ""
