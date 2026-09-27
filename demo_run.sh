#!/usr/bin/env bash
# =============================================================================
# demo_run.sh — Expiry Radar · Full pipeline demo (CLI view, ~90 seconds)
#
# This script walks through every collector step with timing pauses so a
# screen recording captures each stage clearly before switching to the
# Streamlit UI for the visual portion.
#
# DEMO SCRIPT (3-minute recording plan):
#   0:00 – 0:15  Intro + run demo_reset.sh  (show empty state)
#   0:15 – 1:00  Run demo_run.sh            (watch 5 agents fire in terminal)
#   1:00 – 2:30  Switch to Streamlit UI     (walk through 6 tabs)
#   2:30 – 3:00  Backtest tab               (show the headline metric)
# =============================================================================
set -euo pipefail

SCRIPTS=".bob/skills/expiry-radar/scripts"
PYTHON="python3"

# ── Colour helpers ────────────────────────────────────────────────────────────
BOLD=$'\033[1m'; RESET=$'\033[0m'
GREEN=$'\033[32m'; BLUE=$'\033[34m'; YELLOW=$'\033[33m'; CYAN=$'\033[36m'

banner() { echo ""; echo "${BOLD}${BLUE}$1${RESET}"; echo ""; }
step()   { echo "  ${GREEN}▶${RESET}  ${BOLD}$1${RESET}"; }
done_()  { echo "  ${GREEN}✔${RESET}  $1"; }
pause()  { sleep "${1:-1}"; }

# =============================================================================
echo ""
echo "${BOLD}${CYAN}╔══════════════════════════════════════════════════════════╗${RESET}"
echo "${BOLD}${CYAN}║   📡  Expiry Radar — IBM Bob 2.0 Hackathon Demo          ║${RESET}"
echo "${BOLD}${CYAN}║   'Everything has a hidden expiration date. We find it.' ║${RESET}"
echo "${BOLD}${CYAN}╚══════════════════════════════════════════════════════════╝${RESET}"
pause 2

# ── AGENT 1: EOL Collector ────────────────────────────────────────────────────
banner "🤖 Agent 1 / 5 — EOL Collector"
step "Reads requirements.txt, queries endoflife.date API + IBM/Qiskit fallback map"
pause 1
$PYTHON "$SCRIPTS/collect_eol.py"
done_ "eol_candidates.json + eol_findings.json written"
pause 1

# ── AGENT 2: Date & TODO Scanner ─────────────────────────────────────────────
banner "🤖 Agent 2 / 5 — Date & TODO Scanner"
step "Scans all .py/.md files for hardcoded ISO dates and TODO comments"
pause 1
$PYTHON "$SCRIPTS/collect_dates.py"
done_ "candidates.json written (false-positives filtered by comment-anchor regex)"
pause 1

# ── AGENT 3: GitHub Issues Agent ─────────────────────────────────────────────
banner "🤖 Agent 3 / 5 — GitHub Issues Agent"
step "Scans codebase for GitHub issue URLs, checks status via REST API"
step "Flags CLOSED issues with live workaround comments still in the code"
pause 1
$PYTHON "$SCRIPTS/collect_issues.py"
done_ "issue_candidates.json + issue_findings.json written"
pause 1

# ── AGENT 4: Release Notes RAG ───────────────────────────────────────────────
banner "🤖 Agent 4 / 5 — Release Notes RAG"
step "Fetches latest 15 Qiskit GitHub releases"
step "Parses Deprecated/Removed sections → matches against codebase"
pause 1
$PYTHON "$SCRIPTS/collect_release_notes.py"
done_ "deprecation_findings.json written"
pause 1

# ── AGENT 5: Urgency Scorer ──────────────────────────────────────────────────
banner "🤖 Agent 5 / 5 — Urgency Scorer"
step "Merges all findings, scores by urgency = (1/days_left) × severity × confidence"
step "Ranks findings, emits scored_findings.json"
pause 1
$PYTHON "$SCRIPTS/score.py"
done_ "scored_findings.json written"
pause 1

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "${BOLD}${GREEN}══════════════════════════════════════════════════════════${RESET}"
echo "${BOLD}${GREEN}  ✅  All 5 agents complete.${RESET}"
echo "${BOLD}${GREEN}══════════════════════════════════════════════════════════${RESET}"
echo ""

$PYTHON - << 'PYEOF'
import json, datetime

with open("scored_findings.json") as f:
    findings = json.load(f)

counts = {}
for fin in findings:
    counts[fin.get("severity","?")] = counts.get(fin.get("severity","?"), 0) + 1

print(f"  📊  {len(findings)} findings ranked by urgency:")
for sev in ["critical","high","medium","low"]:
    n = counts.get(sev, 0)
    bar = "█" * n
    print(f"       {sev:8s}  {bar}  {n}")

print()
print("  🏆  Top 3 most urgent findings:")
for fin in findings[:3]:
    dl = fin.get("days_left")
    dl_str = f"{dl}d" if dl is not None else "stale"
    print(f"       [{fin['rank']}] {fin['id']}  {fin['severity']:8s}  "
          f"score={fin['urgency_score']:.3f}  {fin['title'][:52]}")

print()
print("  ➡   Now open the Streamlit dashboard:")
print("      streamlit run app.py")
print()
PYEOF

pause 2

# ── Launch Streamlit ──────────────────────────────────────────────────────────
echo "${BOLD}${YELLOW}▶  Launching Streamlit dashboard...${RESET}"
echo "   (If browser doesn't open automatically, go to http://localhost:8501)"
echo ""
streamlit run app.py
