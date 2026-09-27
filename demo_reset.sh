#!/usr/bin/env bash
# =============================================================================
# demo_reset.sh - Expiry Radar · Pre-demo reset
# =============================================================================
# Run ONCE before every demo. Wipes all generated artifacts and resets
# requirements.txt to the unpinned state so the pipeline produces real
# findings during the live demo.
#
# No localhost. No hardcoded branches. Safe to re-run.
# =============================================================================
set -euo pipefail

BOLD=$'\033[1m'; RESET=$'\033[0m'
GREEN=$'\033[32m'; CYAN=$'\033[36m'; YELLOW=$'\033[33m'; RED=$'\033[31m'

banner() { echo ""; echo "${BOLD}${CYAN}══  $1  ${RESET}"; }
ok()     { echo "  ${GREEN}✔${RESET}  $1"; }
warn()   { echo "  ${YELLOW}⚠${RESET}  $1"; }

echo ""
echo "${BOLD}${CYAN}╔══════════════════════════════════════════════════╗${RESET}"
echo "${BOLD}${CYAN}║   📡  Expiry Radar - Pre-Demo Reset              ║${RESET}"
echo "${BOLD}${CYAN}╚══════════════════════════════════════════════════╝${RESET}"

# ── 1. Confirm we are on main ──────────────────────────────────────────────────
banner "Step 1 / 5 - Git state"
CURRENT_BRANCH=$(git branch --show-current)
if [ "$CURRENT_BRANCH" != "main" ]; then
  echo "  ${YELLOW}Currently on branch '${CURRENT_BRANCH}'. Switching to main...${RESET}"
  git checkout main
  ok "On main."
else
  ok "Already on main."
fi

# Delete any local fix branches left over from a previous demo run
for branch in $(git branch | grep "fix/" | tr -d ' '); do
  git branch -D "$branch" 2>/dev/null && warn "Deleted leftover branch: $branch" || true
done

# ── 2. Remove all generated pipeline artifacts ─────────────────────────────────
banner "Step 2 / 5 - Clear pipeline artifacts"
ARTIFACTS=(
  candidates.json
  eol_candidates.json
  eol_findings.json
  deprecation_findings.json
  issue_candidates.json
  issue_findings.json
  todo_findings.json
  todo_analysis.json
  scored_findings.json
  backtest_results.json
)
removed=0
for f in "${ARTIFACTS[@]}"; do
  [ -f "$f" ] && rm -f "$f" && (( removed++ )) || true
done
ok "Removed $removed artifact(s). Working directory is clean."

# ── 3. Reset requirements.txt to unpinned (shows real EOL findings in demo) ───
banner "Step 3 / 5 - Reset requirements.txt to unfixed state"
cat > requirements.txt << 'REQEOF'
requests
packaging
cryptography
rank_bm25
pydantic
streamlit
pandas
REQEOF
ok "requirements.txt reset (unpinned - EOL findings will appear in the pipeline)."

# ── 4. Verify Python dependencies ─────────────────────────────────────────────
banner "Step 4 / 5 - Verify dependencies"
if python3 -c "import streamlit, pandas, packaging, requests, rank_bm25" 2>/dev/null; then
  ok "All required packages importable."
else
  warn "Some packages may be missing. Run: pip install streamlit pandas packaging requests rank_bm25"
fi

# ── 5. Verify collectors ──────────────────────────────────────────────────────
banner "Step 5 / 5 - Verify collector scripts"
SCRIPTS=".bob/skills/expiry-radar/scripts"
ALL_OK=true
for script in collect_eol.py collect_dates.py collect_issues.py collect_release_notes.py score.py; do
  if [ -f "$SCRIPTS/$script" ]; then
    ok "$script present"
  else
    echo "  ${RED}✖${RESET}  MISSING: $SCRIPTS/$script"
    ALL_OK=false
  fi
done

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
if $ALL_OK; then
  echo "${BOLD}${GREEN}✅  Reset complete. You are ready for the demo.${RESET}"
else
  echo "${BOLD}${YELLOW}⚠   Reset complete with warnings - check missing files above.${RESET}"
fi
echo ""
echo "  Next step:"
echo ""
echo "  ${BOLD}Option A - Run full pipeline in terminal (then open Streamlit):${RESET}"
echo "    bash demo_run.sh"
echo ""
echo "  ${BOLD}Option B - Jump straight to the Streamlit app:${RESET}"
echo "    1. Open your Streamlit Cloud app URL"
echo "    2. Click  🔄 Run All Collectors  in the sidebar"
echo "    3. Walk through the 6 tabs"
echo "    4. Auto-Fix → Step 2 → Apply fixes → Step 4 → Open PR on GitHub"
echo ""
