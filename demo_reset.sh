#!/usr/bin/env bash
# =============================================================================
# demo_reset.sh — Expiry Radar · Pre-demo reset
# Run this ONCE before starting the demo recording.
# Clears all generated artifacts and resets requirements.txt to "unfixed" state
# so every step of the pipeline produces visible output during the demo.
# =============================================================================
set -euo pipefail

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║   📡  Expiry Radar — Pre-Demo Reset              ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# ── 1. Remove all generated JSON artifacts ────────────────────────────────────
echo "▶  Clearing generated pipeline artifacts..."
rm -f candidates.json \
      eol_candidates.json \
      eol_findings.json \
      deprecation_findings.json \
      issue_candidates.json \
      issue_findings.json \
      todo_findings.json \
      todo_analysis.json \
      scored_findings.json \
      backtest_results.json
echo "   ✔  Artifacts cleared."

# ── 2. Reset requirements.txt to unpinned (shows real EOL issues in demo) ─────
echo "▶  Resetting requirements.txt to unpinned state..."
cat > requirements.txt << 'REQEOF'
requests
packaging
cryptography
rank_bm25
pydantic
streamlit
pandas
REQEOF
echo "   ✔  requirements.txt reset."

# ── 3. Verify Streamlit is installed ─────────────────────────────────────────
echo "▶  Checking dependencies..."
python3 -c "import streamlit, pandas, packaging, requests" 2>/dev/null \
  && echo "   ✔  All required packages available." \
  || { echo "   ⚠  Run: pip install -r requirements.txt"; }

echo ""
echo "✅  Reset complete. You are ready to record."
echo ""
echo "   Start the demo with:  bash demo_run.sh"
echo "   Or launch the app:    streamlit run app.py"
echo ""
