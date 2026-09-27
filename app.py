"""
app.py - Expiry Radar · Streamlit Dashboard
---------------------------------------------
Run:  streamlit run app.py
"""

import json
import os
import re
import subprocess
import sys
import datetime

import streamlit as st

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Expiry Radar",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Theme tokens (inline CSS) ────────────────────────────────────────────────
SEV_COLOR = {
    "critical": "#d73027",
    "high":     "#fc8d59",
    "medium":   "#fee090",
    "low":      "#91bfdb",
    "unknown":  "#cccccc",
}
SEV_BG = {
    "critical": "#fff0f0",
    "high":     "#fff7f0",
    "medium":   "#fffdf0",
    "low":      "#f0f7ff",
    "unknown":  "#f5f5f5",
}
CAT_ICON = {
    "eol":         "⏱️",
    "deprecation": "🔕",
    "workaround":  "🩹",
    "todo":        "📝",
}

st.markdown("""
<style>
/* card */
.finding-card {
    border-radius: 8px;
    padding: 14px 18px;
    margin-bottom: 10px;
    border-left: 5px solid;
}
/* severity badge */
.badge {
    display: inline-block;
    border-radius: 4px;
    padding: 1px 8px;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: .04em;
    text-transform: uppercase;
    color: #fff;
    margin-right: 6px;
}
.badge-critical { background:#d73027; }
.badge-high     { background:#fc8d59; color:#222; }
.badge-medium   { background:#fee090; color:#222; }
.badge-low      { background:#91bfdb; color:#222; }
/* timeline bar container */
.tl-bar-bg {
    background: #e5e7eb;
    border-radius: 4px;
    height: 12px;
    width: 100%;
}
.tl-bar-fill {
    height: 12px;
    border-radius: 4px;
}
/* metric row */
.metric-box {
    text-align: center;
    padding: 12px 8px;
    border-radius: 8px;
    background: #f7f8fa;
}
.metric-num  { font-size: 2rem; font-weight: 700; line-height: 1; }
.metric-lab  { font-size: 0.78rem; color: #57606a; margin-top: 2px; }
/* fix workflow */
.fix-card-done     { background:#f0fff4; border:1.5px solid #3fb950; border-radius:8px; padding:12px 16px; margin-bottom:8px; }
.fix-card-upstream { background:#f7f8fa; border:1.5px solid #e5e7eb; border-radius:8px; padding:12px 16px; margin-bottom:8px; }
.fix-card-blocked  { background:#fff8f0; border:1.5px solid #fc8d59; border-radius:8px; padding:12px 16px; margin-bottom:8px; }
.fix-step { font-family:"IBM Plex Mono",monospace; font-size:0.8rem; }
.pr-box { background:#0d1117; color:#e6edf3; border-radius:8px; padding:16px 20px;
          font-family:"IBM Plex Mono",monospace; font-size:0.82rem; line-height:1.8; }
/* agentic trace panel */
.agent-panel {
    background: #0d1117;
    border-radius: 8px;
    padding: 16px 20px;
    font-family: "IBM Plex Mono", "SFMono-Regular", Consolas, monospace;
    font-size: 0.82rem;
    line-height: 1.7;
    color: #e6edf3;
    margin-bottom: 12px;
}
.agent-step-pending  { color: #57606a; }
.agent-step-running  { color: #f0a500; font-weight: 600; }
.agent-step-done     { color: #3fb950; font-weight: 600; }
.agent-step-error    { color: #f85149; font-weight: 600; }
.agent-step-output   { color: #8b949e; margin-left: 22px; white-space: pre-wrap; }
</style>
""", unsafe_allow_html=True)

# ── Helpers ───────────────────────────────────────────────────────────────────

SCORED_PATH = "scored_findings.json"
SCRIPTS_DIR = os.path.join(".bob", "skills", "expiry-radar", "scripts")


def _short_path(full_path: str) -> str:
    """Trim absolute prefix to a readable relative path."""
    try:
        return os.path.relpath(full_path)
    except ValueError:
        return full_path


def _badge(sev: str) -> str:
    cls = f"badge-{sev}" if sev in SEV_COLOR else "badge-low"
    return f'<span class="badge {cls}">{sev}</span>'


def _bar(days_left, max_days: int = 400) -> str:
    """Render a coloured urgency bar. Clamped to [0, max_days]."""
    if days_left is None:
        pct = 60  # workaround - no deadline, show as orange-level
        color = SEV_COLOR["high"]
    elif days_left <= 0:
        pct = 100
        color = SEV_COLOR["critical"]
    else:
        pct = max(0, min(100, int((1 - days_left / max_days) * 100)))
        color = SEV_COLOR["critical"] if pct >= 85 else (
            SEV_COLOR["high"] if pct >= 60 else (
                SEV_COLOR["medium"] if pct >= 30 else SEV_COLOR["low"]
            )
        )
    return (
        f'<div class="tl-bar-bg">'
        f'<div class="tl-bar-fill" style="width:{pct}%;background:{color};"></div>'
        f'</div>'
    )


def load_findings() -> list[dict]:
    if not os.path.exists(SCORED_PATH):
        return []
    with open(SCORED_PATH) as f:
        return json.load(f)


# ── Agentic pipeline definition ───────────────────────────────────────────────
# Each entry: (script_filename, agent_label, description_of_what_it_does)
PIPELINE_STEPS = [
    (
        "collect_eol.py",
        "EOL Collector",
        "Reads requirements.txt, queries endoflife.date API + IBM/Qiskit fallback map, "
        "emits eol_findings.json",
    ),
    (
        "collect_dates.py",
        "Date & TODO Scanner",
        "Scans all .py and .md files for hardcoded ISO dates and TODO comments "
        "anchored to a code comment marker, emits candidates.json",
    ),
    (
        "collect_issues.py",
        "GitHub Issues Agent",
        "Scans codebase for GitHub issue URLs, calls GitHub REST API to check "
        "current state, flags closed issues with live workarounds, emits "
        "issue_findings.json",
    ),
    (
        "collect_release_notes.py",
        "Release Notes RAG",
        "Fetches latest Qiskit GitHub releases, extracts Deprecated/Removed "
        "sections, cross-references against a curated IBM/Qiskit deprecation "
        "catalog, scans codebase for matches, emits deprecation_findings.json",
    ),
    (
        "score.py",
        "Urgency Scorer",
        "Merges all findings sources, computes urgency_score = "
        "(1/days_left) × severity_weight × confidence, ranks all findings, "
        "emits scored_findings.json",
    ),
]


def run_pipeline_streaming(trace_slot, log_slot) -> bool:
    """
    Run each pipeline step sequentially, updating a live Streamlit placeholder
    with a tick-mark trace panel after every step completes.

    trace_slot : st.empty() - receives the growing step checklist
    log_slot   : st.empty() - receives the raw stdout log accordion
    """
    states: list[str] = ["pending"] * len(PIPELINE_STEPS)
    outputs: list[str] = [""] * len(PIPELINE_STEPS)
    all_ok = True

    def _render_trace():
        lines = ['<div class="agent-panel">']
        lines.append(
            '<span style="color:#58a6ff;font-weight:700;font-size:0.9rem">'
            '📡 Expiry Radar · Agentic Pipeline</span><br/>'
        )
        for i, (_, label, desc) in enumerate(PIPELINE_STEPS):
            s = states[i]
            if s == "pending":
                icon  = "○"
                cls   = "agent-step-pending"
            elif s == "running":
                icon  = "◌"
                cls   = "agent-step-running"
            elif s == "done":
                icon  = "✔"
                cls   = "agent-step-done"
            else:  # error
                icon  = "✖"
                cls   = "agent-step-error"

            lines.append(
                f'<span class="{cls}">{icon} <strong>Step {i+1}: {label}</strong></span>'
                f'<br/>'
                f'<span class="agent-step-output">{desc}</span><br/>'
            )
            if outputs[i]:
                # indent each output line
                out_html = outputs[i].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                for out_line in out_html.splitlines():
                    lines.append(
                        f'<span class="agent-step-output">&nbsp;&nbsp;&nbsp;&nbsp;{out_line}</span><br/>'
                    )
            lines.append("<br/>")
        lines.append("</div>")
        trace_slot.markdown("\n".join(lines), unsafe_allow_html=True)

    full_log: list[str] = []

    for i, (script, label, _) in enumerate(PIPELINE_STEPS):
        states[i] = "running"
        _render_trace()

        path   = os.path.join(SCRIPTS_DIR, script)
        result = subprocess.run(
            [sys.executable, path],
            capture_output=True, text=True, timeout=90,
        )

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        if result.returncode == 0:
            states[i]  = "done"
            outputs[i] = stdout or "(no output)"
        else:
            states[i]  = "error"
            outputs[i] = (stdout + "\n⚠ " + stderr[:300]).strip()
            all_ok = False

        full_log.append(f"▶ {script}  (exit {result.returncode})")
        if stdout:
            full_log.append(stdout)
        if result.returncode != 0 and stderr:
            full_log.append(f"⚠ stderr: {stderr[:400]}")

        _render_trace()

    log_slot.code("\n".join(full_log), language="text")
    return all_ok


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.image(
        "https://upload.wikimedia.org/wikipedia/commons/5/51/IBM_logo.svg",
        width=120,
    )
    st.markdown("## 📡 Expiry Radar")
    st.caption("IBM Bob 2.0 Hackathon · Team Project")
    st.divider()

    st.markdown("### Filters")
    sev_filter = st.multiselect(
        "Severity",
        options=["critical", "high", "medium", "low"],
        default=["critical", "high", "medium", "low"],
    )
    cat_filter = st.multiselect(
        "Category",
        options=["eol", "deprecation", "workaround", "todo"],
        default=["eol", "deprecation", "workaround", "todo"],
    )
    show_closed = st.checkbox("Show resolved", value=False)

    st.divider()
    st.markdown("### Re-run Pipeline")
    st.caption("Runs all collectors and re-scores findings.")
    if st.button("🔄  Run All Collectors", use_container_width=True):
        st.session_state["show_trace"] = True
        st.rerun()

    st.divider()
    st.caption(f"Data: `{SCORED_PATH}`")
    st.caption(f"Last refreshed: {datetime.datetime.now().strftime('%H:%M:%S')}")

# ── Main header ───────────────────────────────────────────────────────────────

st.markdown("# 📡 Expiry Radar")
st.markdown(
    "*Everything in a codebase has a hidden expiration date. "
    "We find it before production does.*"
)
st.divider()

# ── Agentic trace panel (shown when pipeline is triggered) ────────────────────
if st.session_state.get("show_trace"):
    st.markdown("## 🤖 Agentic Pipeline - Live Trace")
    st.caption(
        "Each subagent runs sequentially. Watch the tick marks as each collector "
        "completes and hands off to the next."
    )

    trace_slot = st.empty()
    log_slot   = st.empty()

    ok = run_pipeline_streaming(trace_slot, log_slot)

    if ok:
        st.success("✅  All agents completed. Findings refreshed - scroll down to see results.")
    else:
        st.error("⚠️  One or more agents reported errors. Check the log above.")

    with st.expander("📄  Full pipeline log"):
        pass  # already rendered into log_slot above

    st.session_state["show_trace"] = False
    st.divider()

# ── Load data ─────────────────────────────────────────────────────────────────

all_findings = load_findings()

if not all_findings:
    st.info(
        "No scored findings yet.  \n"
        "Click **Run All Collectors** in the sidebar, or run:  \n"
        "```\npython .bob/skills/expiry-radar/scripts/score.py\n```"
    )
    st.stop()

# Apply filters
findings = [
    f for f in all_findings
    if f.get("severity") in sev_filter
    and f.get("category") in cat_filter
    and (show_closed or f.get("status") != "resolved")
]

# ── KPI metrics ───────────────────────────────────────────────────────────────

total     = len(findings)
n_crit    = sum(1 for f in findings if f.get("severity") == "critical")
n_high    = sum(1 for f in findings if f.get("severity") == "high")
n_med     = sum(1 for f in findings if f.get("severity") == "medium")
n_low     = sum(1 for f in findings if f.get("severity") == "low")
past_due  = sum(1 for f in findings if (f.get("days_left") or 1) <= 0)

col1, col2, col3, col4, col5, col6 = st.columns(6)
for col, num, label, color in [
    (col1, total,   "Total",    "#1f2328"),
    (col2, n_crit,  "Critical", SEV_COLOR["critical"]),
    (col3, n_high,  "High",     SEV_COLOR["high"]),
    (col4, n_med,   "Medium",   SEV_COLOR["medium"]),
    (col5, n_low,   "Low",      SEV_COLOR["low"]),
    (col6, past_due,"Past Due", SEV_COLOR["critical"]),
]:
    col.markdown(
        f'<div class="metric-box">'
        f'<div class="metric-num" style="color:{color}">{num}</div>'
        f'<div class="metric-lab">{label}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

st.divider()

# ── Tabs ──────────────────────────────────────────────────────────────────────

tab_timeline, tab_calendar, tab_table, tab_detail, tab_autofix, tab_backtest = st.tabs([
    "⏱  Timeline", "📅  Calendar", "📋  All Findings", "🔍  Detail", "🔧  Auto-Fix", "🧪  Backtest"
])

# ─────────────────────────────────────────────────────────────────────────────
# TAB 1 - Timeline (horizontal urgency bars sorted by rank)
# ─────────────────────────────────────────────────────────────────────────────

with tab_timeline:
    st.markdown("### Breaking Changes Timeline")
    st.caption(
        "Bars show urgency - longer/redder = closer to deadline. "
        "Workarounds (no deadline) are shown in orange."
    )

    # Split into "has date" and "workarounds"
    dated   = [f for f in findings if f.get("breaks_on")]
    undated = [f for f in findings if not f.get("breaks_on")]

    dated.sort(key=lambda f: f.get("breaks_on") or "9999")

    for f in dated + undated:
        sev     = f.get("severity", "unknown")
        cat     = f.get("category", "")
        icon    = CAT_ICON.get(cat, "•")
        title   = f.get("title", "Untitled")
        fid     = f.get("id", "")
        dl      = f.get("days_left")
        breaks  = f.get("breaks_on", "-")
        score   = f.get("urgency_score", 0)
        rank    = f.get("rank", "?")

        dl_label = (
            f"{dl}d left" if dl and dl > 0
            else ("**PAST DUE**" if dl is not None and dl <= 0
                  else f"stale {f['evidence'].get('days_since_closed', '?')}d")
            if "evidence" in f else "no deadline"
        )

        border_col = SEV_COLOR.get(sev, "#ccc")
        bg_col     = SEV_BG.get(sev, "#fff")

        st.markdown(
            f'<div class="finding-card" style="border-color:{border_col};background:{bg_col};">'
            f'{_badge(sev)}'
            f'<strong>{icon} [{fid}]</strong> {title}<br/>'
            f'<small style="color:#57606a">Breaks: <strong>{breaks}</strong> &nbsp;|&nbsp; '
            f'{dl_label} &nbsp;|&nbsp; Score: {score:.4f} &nbsp;|&nbsp; Rank #{rank}</small>'
            f'</div>',
            unsafe_allow_html=True,
        )
        st.markdown(_bar(dl), unsafe_allow_html=True)
        st.markdown("<div style='margin-bottom:4px'></div>", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# TAB 2 - Calendar (month-grouped list of upcoming breaks)
# ─────────────────────────────────────────────────────────────────────────────

with tab_calendar:
    st.markdown("### Breakage Calendar")
    st.caption("Findings grouped by the month they are projected to break.")

    dated_cal = sorted(
        [f for f in findings if f.get("breaks_on")],
        key=lambda f: f["breaks_on"],
    )

    if not dated_cal:
        st.info("No findings with explicit deadline dates match current filters.")
    else:
        from itertools import groupby

        def _month_key(f):
            return f["breaks_on"][:7]  # YYYY-MM

        for month, group in groupby(dated_cal, key=_month_key):
            items = list(group)
            worst_sev = min(
                items,
                key=lambda f: ["critical", "high", "medium", "low"].index(
                    f.get("severity", "low")
                ),
            )["severity"]
            color = SEV_COLOR.get(worst_sev, "#ccc")

            try:
                month_label = datetime.date.fromisoformat(month + "-01").strftime("%B %Y")
            except ValueError:
                month_label = month

            st.markdown(
                f'<div style="border-left:4px solid {color};padding-left:12px;margin:16px 0 4px">'
                f'<strong style="font-size:1.05rem">{month_label}</strong> '
                f'<span style="color:#57606a;font-size:0.85rem">- {len(items)} finding(s)</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

            for f in items:
                sev   = f.get("severity", "unknown")
                icon  = CAT_ICON.get(f.get("category", ""), "•")
                dl    = f.get("days_left")
                dl_s  = f"{dl}d" if dl is not None else "?"
                st.markdown(
                    f"&nbsp;&nbsp;{_badge(sev)} {icon} **{f['id']}** - "
                    f"{f.get('title','?')} *(in {dl_s})*",
                    unsafe_allow_html=True,
                )

        # Past-due section
        past = [f for f in findings if f.get("days_left") is not None and f["days_left"] <= 0]
        if past:
            st.markdown(
                f'<div style="border-left:4px solid {SEV_COLOR["critical"]};'
                f'padding-left:12px;margin:20px 0 4px">'
                f'<strong style="font-size:1.05rem;color:{SEV_COLOR["critical"]}">⚠ Past Due</strong> '
                f'<span style="color:#57606a;font-size:0.85rem">- {len(past)} finding(s) already overdue</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
            for f in past:
                sev  = f.get("severity", "unknown")
                icon = CAT_ICON.get(f.get("category", ""), "•")
                st.markdown(
                    f"&nbsp;&nbsp;{_badge(sev)} {icon} **{f['id']}** - "
                    f"{f.get('title','?')} *(broke on {f.get('breaks_on','?')})*",
                    unsafe_allow_html=True,
                )

# ─────────────────────────────────────────────────────────────────────────────
# TAB 3 - All Findings table
# ─────────────────────────────────────────────────────────────────────────────

with tab_table:
    st.markdown("### All Findings")

    rows = []
    for f in findings:
        ev = f.get("evidence", {})
        locs = ev.get("all_locations") or [ev.get("code", "")]
        rows.append({
            "Rank":      f.get("rank"),
            "ID":        f.get("id"),
            "Severity":  f.get("severity", "?").upper(),
            "Category":  f.get("category", "?"),
            "Title":     f.get("title", "?"),
            "Breaks On": f.get("breaks_on") or "-",
            "Days Left": f.get("days_left"),
            "Score":     f.get("urgency_score"),
            "Locations": len(locs),
            "Fix":       f.get("fix", "?"),
        })

    import pandas as pd
    df = pd.DataFrame(rows)

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Score":     st.column_config.NumberColumn(format="%.4f"),
            "Locations": st.column_config.NumberColumn("Files"),
        },
    )

    csv = df.to_csv(index=False)
    st.download_button(
        "⬇  Download CSV",
        data=csv,
        file_name="expiry_radar_findings.csv",
        mime="text/csv",
    )

# ─────────────────────────────────────────────────────────────────────────────
# TAB 4 - Detail drilldown
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# TAB 5 - Auto-Fix workflow
# ─────────────────────────────────────────────────────────────────────────────

with tab_autofix:
    st.markdown("### 🔧 Auto-Fix Workflow")
    st.caption(
        "Expiry Radar reviews every high-severity finding, applies fixes it can make "
        "directly in this repo, then prepares a PR. Upstream Qiskit items are flagged "
        "with the correct upstream repo link."
    )

    # ── Step 1: Triage ────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### Step 1 - Triage findings by fixability")

    # Classify every finding
    FIXABLE     = []   # can be fixed in this repo right now
    UPSTREAM    = []   # lives in vendored qiskit-machine-learning - needs upstream PR
    NO_DEADLINE = []   # workarounds - needs manual review

    for fin in all_findings:
        ev    = fin.get("evidence", {})
        locs  = ev.get("all_locations") or [ev.get("code", "")]
        in_vendor = any("qiskit-machine-learning" in (l or "") for l in locs)
        if fin.get("category") == "workaround":
            NO_DEADLINE.append(fin)
        elif in_vendor:
            UPSTREAM.append(fin)
        else:
            FIXABLE.append(fin)

    col_a, col_b, col_c = st.columns(3)
    col_a.markdown(
        f'<div style="text-align:center;padding:10px;background:#f0fff4;border-radius:8px">'
        f'<div style="font-size:1.8rem;font-weight:700;color:#3fb950">{len(FIXABLE)}</div>'
        f'<div style="font-size:0.78rem;color:#57606a">Auto-fixable in this repo</div></div>',
        unsafe_allow_html=True,
    )
    col_b.markdown(
        f'<div style="text-align:center;padding:10px;background:#f7f8fa;border-radius:8px">'
        f'<div style="font-size:1.8rem;font-weight:700;color:#57606a">{len(UPSTREAM)}</div>'
        f'<div style="font-size:0.78rem;color:#57606a">Upstream Qiskit - needs upstream PR</div></div>',
        unsafe_allow_html=True,
    )
    col_c.markdown(
        f'<div style="text-align:center;padding:10px;background:#fff8f0;border-radius:8px">'
        f'<div style="font-size:1.8rem;font-weight:700;color:#fc8d59">{len(NO_DEADLINE)}</div>'
        f'<div style="font-size:0.78rem;color:#57606a">Stale workarounds - manual review</div></div>',
        unsafe_allow_html=True,
    )

    # ── Step 2: Apply fixes ───────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### Step 2 - Apply fixes")

    # Describe what each fixable item needs
    FIX_ACTIONS: dict[str, dict] = {
        "EOL-001": {
            "file":    "requirements.txt",
            "old":     r"^cryptography$",
            "new":     "cryptography>=44.0.0",
            "reason":  "cryptography <44 reached EOL. Pin to >=44.0.0 (latest: 50.0.1).",
            "ref":     "https://cryptography.io/en/latest/changelog/",
        },
        "EOL-002": {
            "file":    "requirements.txt",
            "old":     r"^pydantic$",
            "new":     "pydantic>=2.0.0",
            "reason":  "pydantic v1 EOL was 2024-06-30. Pin to >=2.0.0 (latest: 2.13.5).",
            "ref":     "https://docs.pydantic.dev/latest/migration/",
        },
    }

    def _apply_req_fix(fid: str, action: dict) -> tuple[bool, str]:
        """Apply a single requirements.txt line replacement. Returns (changed, new_content)."""
        try:
            with open(action["file"]) as f:
                content = f.read()
            new_content = re.sub(action["old"], action["new"], content, flags=re.MULTILINE)
            already_fixed = action["new"] in content
            if not already_fixed:
                with open(action["file"], "w") as f:
                    f.write(new_content)
            return True, new_content
        except Exception as exc:
            return False, str(exc)

    def _read_req() -> str:
        try:
            with open("requirements.txt") as f:
                return f.read()
        except Exception:
            return ""

    if FIXABLE:
        for fin in FIXABLE:
            fid  = fin["id"]
            sev  = fin.get("severity", "low")
            act  = FIX_ACTIONS.get(fid)
            ev   = fin.get("evidence", {})

            border = SEV_COLOR.get(sev, "#ccc")
            st.markdown(
                f'<div class="fix-card-done" style="border-color:{border}">'
                f'{_badge(sev)} <strong>{fid}</strong> - {fin.get("title","")}</div>',
                unsafe_allow_html=True,
            )

            if act:
                c1, c2 = st.columns([3, 1])
                with c1:
                    st.markdown(f"**Fix:** `{act['file']}` - `{act['new']}`")
                    st.caption(act["reason"])
                    st.markdown(f"📎 [{act['ref']}]({act['ref']})")
                with c2:
                    btn_key = f"fix_{fid}"
                    if st.button(f"✅  Apply fix", key=btn_key, use_container_width=True):
                        ok, content = _apply_req_fix(fid, act)
                        if ok:
                            st.session_state[f"fixed_{fid}"] = True
                            st.success(f"Applied! `{act['file']}` updated.")
                        else:
                            st.error(f"Failed: {content}")

                # Show current file state
                if st.session_state.get(f"fixed_{fid}"):
                    st.code(_read_req(), language="text")
            else:
                st.info("Fix details: see evidence source link in the Detail tab.")
            st.markdown("")
    else:
        st.info("No directly auto-fixable items match current filters.")

    # ── Step 3: Upstream items ────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### Step 3 - Upstream Qiskit items")
    st.caption(
        "These findings live inside the vendored `qiskit-machine-learning` source. "
        "Patching them here would be overwritten on next install. "
        "The correct fix is a PR to the upstream repository."
    )

    UPSTREAM_LINKS: dict[str, str] = {
        "DEP-001": "https://github.com/qiskit-community/qiskit-machine-learning/issues/new?title=Migrate+BaseSamplerV1+to+V2",
        "DEP-002": "https://github.com/qiskit-community/qiskit-machine-learning/issues/new?title=Migrate+BaseEstimatorV1+to+V2",
        "DEP-003": "https://github.com/qiskit-community/qiskit-machine-learning/issues/new?title=Migrate+QuasiDistribution+to+SamplerPubResult",
        "DEP-004": "https://github.com/qiskit-community/qiskit-machine-learning/issues/new?title=Remove+qiskit.providers.Options+usage",
        "DEP-005": "https://github.com/qiskit-community/qiskit-machine-learning/issues/new?title=Migrate+PrimitiveJob+to+BasePrimitiveJob",
        "DEP-006": "https://github.com/qiskit-community/qiskit-machine-learning/issues/new?title=Remove+ParameterValueType+usage",
        "ISS-001": "https://github.com/qiskit-community/qiskit-machine-learning/issues/new?title=Remove+stale+workaround+for+%23716",
        "ISS-002": "https://github.com/qiskit-community/qiskit-machine-learning/issues/new?title=Remove+stale+workaround+for+%23570",
    }

    UPSTREAM_MIGRATIONS: dict[str, str] = {
        "DEP-001": "Replace `BaseSamplerV1` with `BaseSamplerV2`. V2 `.run()` takes PUBs, not circuits + params separately.",
        "DEP-002": "Replace `BaseEstimatorV1` with `BaseEstimatorV2`. V2 `.run()` takes `EstimatorPub` objects.",
        "DEP-003": "Replace `QuasiDistribution` with `SamplerPubResult` / `BitArray` from V2 sampler results.",
        "DEP-004": "Replace `from qiskit.providers import Options` with `BackendV2`-native options dict.",
        "DEP-005": "Replace `PrimitiveJob` subclass with `BasePrimitiveJob` or return the V2 primitive job directly.",
        "DEP-006": "Replace `ParameterValueType` annotation with `float | ParameterExpression` inline.",
        "ISS-001": "Issue #716 closed Apr 2024. Remove the workaround comment block from `test_torch_connector.py:409-420`.",
        "ISS-002": "Issue #570 closed Feb 2024. Remove the workaround comment from `test_optimizers.py:210`.",
    }

    if UPSTREAM + NO_DEADLINE:
        for fin in UPSTREAM + NO_DEADLINE:
            fid  = fin["id"]
            sev  = fin.get("severity", "low")
            ev   = fin.get("evidence", {})
            locs = ev.get("all_locations") or [ev.get("code", "")]

            st.markdown(
                f'<div class="fix-card-upstream">'
                f'{_badge(sev)} <strong>{fid}</strong> - {fin.get("title","")}</div>',
                unsafe_allow_html=True,
            )

            migration = UPSTREAM_MIGRATIONS.get(fid, "")
            if migration:
                st.markdown(f"**Migration:** {migration}")

            c_loc, c_btn = st.columns([4, 1])
            with c_loc:
                st.caption(f"Primary location: `{_short_path(locs[0])}`")
                if len(locs) > 1:
                    st.caption(f"… and {len(locs)-1} more location(s)")
            with c_btn:
                link = UPSTREAM_LINKS.get(fid, "https://github.com/qiskit-community/qiskit-machine-learning/issues/new")
                st.link_button("↗  File upstream issue", link, use_container_width=True)
            st.markdown("")
    else:
        st.info("No upstream items in current filters.")

    # ── Step 4: PR creation (Seamless Web Flow for Streamlit Cloud) ───────────
    st.markdown("---")
    st.markdown("#### Step 4 - Create Pull Request")
    
    # Read live requirements.txt state to check if fixes were clicked
    def _read_req() -> str:
        try:
            with open("requirements.txt") as f:
                return f.read()
        except Exception:
            return ""
            
    req_content  = _read_req()
    eol001_fixed = "cryptography>=" in req_content
    eol002_fixed = "pydantic>="     in req_content
    fixes_applied = eol001_fixed and eol002_fixed

    if fixes_applied:
        st.info(
            "🔵  Fixes have been verified. Because we are running on Streamlit Cloud, "
            "we jump straight to GitHub to commit them and open the PR seamlessly."
        )

        gh_repo = "rishma1999/expiry-radar"
        gh_edit_url = f"https://github.com/{gh_repo}/edit/main/requirements.txt"
        
        st.markdown(f'''
        <a href="{gh_edit_url}" target="_blank" style="text-decoration:none;">
            <div style="background-color:#2ea043;color:white;padding:12px 20px;text-align:center;border-radius:6px;font-weight:600;margin-top:10px;margin-bottom:10px;font-size:16px;">
                🚀 Jump to GitHub to Create PR
            </div>
        </a>
        ''', unsafe_allow_html=True)
        
        st.caption(
            "**How it works:** This will open `requirements.txt` directly on GitHub. "
            "Simply change `cryptography` to `cryptography>=44.0.0` and `pydantic` to `pydantic>=2.0.0`, "
            "then click **Commit changes...** to instantly create a Pull Request!"
        )
    else:
        st.warning("Apply the fixes in Step 2 above first, then the PR creation link will appear here.")

    # Upstream summary table
    st.markdown("---")
    st.markdown("#### Summary - What's been fixed vs what needs upstream work")

    import pandas as pd
    fix_rows = []
    for fin in all_findings:
        fid = fin["id"]
        ev  = fin.get("evidence", {})
        locs = ev.get("all_locations") or [ev.get("code", "")]
        in_vendor = any("qiskit-machine-learning" in (l or "") for l in locs)
        if fin.get("category") == "workaround":
            action_str = "🔶 Remove stale comment"
            where      = "Upstream: qiskit-community/qiskit-machine-learning"
        elif in_vendor:
            action_str = "🔷 Migrate API"
            where      = "Upstream: qiskit-community/qiskit-machine-learning"
        else:
            action_str = "✅ Version pin"
            where      = "This repo (committed)"
        fix_rows.append({
            "ID":       fid,
            "Severity": fin.get("severity", "?").upper(),
            "Title":    fin.get("title", "?")[:55],
            "Fix type": action_str,
            "Where":    where,
        })

    st.dataframe(pd.DataFrame(fix_rows), use_container_width=True, hide_index=True)


with tab_detail:
    st.markdown("### Finding Detail")

    id_options = [f"{f['rank']:02d}. [{f['id']}] {f['title'][:70]}" for f in findings]
    selected   = st.selectbox("Select a finding", options=id_options)

    if selected:
        idx = id_options.index(selected)
        f   = findings[idx]
        sev = f.get("severity", "unknown")
        ev  = f.get("evidence", {})

        # Header card
        border_col = SEV_COLOR.get(sev, "#ccc")
        bg_col     = SEV_BG.get(sev, "#fff")
        st.markdown(
            f'<div class="finding-card" style="border-color:{border_col};background:{bg_col};">'
            f'{_badge(sev)}'
            f'<strong style="font-size:1.1rem">{f.get("id")} - {f.get("title")}</strong>'
            f'</div>',
            unsafe_allow_html=True,
        )

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Severity",  sev.upper())
        c2.metric("Rank",      f"#{f.get('rank')}")
        c3.metric("Urgency",   f"{f.get('urgency_score', 0):.4f}")
        c4.metric("Days Left", f.get("days_left") if f.get("days_left") is not None else "N/A")

        st.divider()

        col_l, col_r = st.columns([1, 1])

        with col_l:
            st.markdown("**Finding info**")
            st.markdown(f"- **Category:** {CAT_ICON.get(f.get('category',''), '')} {f.get('category','?')}")
            st.markdown(f"- **Breaks on:** {f.get('breaks_on') or '-'}")
            st.markdown(f"- **Confidence:** {f.get('confidence', '?')}")
            st.markdown(f"- **Fix type:** {f.get('fix', '?')}")
            st.markdown(f"- **Status:** {f.get('status', '?')}")

            if ev.get("description"):
                st.markdown("**Description**")
                st.info(ev["description"])

            if ev.get("migration"):
                st.markdown("**Migration guidance**")
                st.success(ev["migration"])

        with col_r:
            st.markdown("**Evidence**")
            source = ev.get("source", "")
            if source:
                st.markdown(f"📎 [Source / Reference]({source})")

            locs = ev.get("all_locations") or [ev.get("code", "")]
            if locs:
                st.markdown(f"**{len(locs)} location(s) in codebase:**")
                for loc in locs:
                    st.code(_short_path(loc), language="text")

            if ev.get("days_since_closed"):
                st.markdown(
                    f"⏳ Workaround stale for **{ev['days_since_closed']} days** "
                    f"(closed: {ev.get('issue_closed_at', '?')[:10]})"
                )

        st.divider()
        with st.expander("Raw JSON"):
            st.json(f)

# ─────────────────────────────────────────────────────────────────────────────
# TAB 6 - Backtesting
# ─────────────────────────────────────────────────────────────────────────────

with tab_backtest:
    import sys as _sys
    _sys.path.insert(0, SCRIPTS_DIR)
    from backtest import run_backtest

    st.markdown("### 🧪 Backtest - Did Expiry Radar work?")
    st.caption(
        "Simulates running Expiry Radar against **qiskit-machine-learning 0.6.0** "
        "(March 2023) and checks how accurately it would have predicted the breakages "
        "that shipped in **0.7.0** (November 2023) - 7.5 months later."
    )

    r = run_backtest()

    # ── Headline banner ───────────────────────────────────────────────────────
    st.markdown(
        f'<div style="background:linear-gradient(135deg,#0d1117 60%,#161b22);'
        f'border-radius:10px;padding:22px 28px;margin-bottom:18px;'
        f'border-left:5px solid #3fb950">'
        f'<div style="font-size:1.35rem;font-weight:700;color:#e6edf3;line-height:1.4">'
        f'📣 &nbsp;"{r["headline"]}"</div>'
        f'<div style="color:#8b949e;font-size:0.82rem;margin-top:8px">'
        f'Snapshot: {r["snapshot"]} ({r["snapshot_date"]}) &nbsp;→&nbsp; '
        f'Evaluated against: {r["evaluated_against"]} ({r["evaluation_date"]})'
        f'</div></div>',
        unsafe_allow_html=True,
    )

    # ── KPI row ───────────────────────────────────────────────────────────────
    k1, k2, k3, k4, k5 = st.columns(5)
    for col, val, label, color in [
        (k1, f"{r['precision']:.0%}",      "Precision",      "#3fb950"),
        (k2, f"{r['recall']:.0%}",         "Recall",         "#58a6ff"),
        (k3, f"{r['f1']:.2f}",             "F1 Score",       "#a371f7"),
        (k4, f"{r['avg_lead_months']}mo",  "Avg Lead Time",  "#f0a500"),
        (k5, f"{r['tp']}/{r['total_actual_broke']}",
                                            "Breakages Found","#3fb950"),
    ]:
        col.markdown(
            f'<div class="metric-box">'
            f'<div class="metric-num" style="color:{color}">{val}</div>'
            f'<div class="metric-lab">{label}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.divider()

    # ── Confusion matrix ──────────────────────────────────────────────────────
    col_cm, col_legend = st.columns([1, 2])

    with col_cm:
        st.markdown("**Confusion matrix**")
        cm_html = (
            '<table style="border-collapse:collapse;font-size:0.9rem;width:100%">'
            '<tr><td></td>'
            '<th style="padding:8px;background:#161b22;color:#8b949e;text-align:center">Actually broke</th>'
            '<th style="padding:8px;background:#161b22;color:#8b949e;text-align:center">Didn\'t break</th></tr>'
            f'<tr><th style="padding:8px;background:#161b22;color:#8b949e">Radar flagged</th>'
            f'<td style="padding:12px;background:#0d3320;color:#3fb950;font-weight:700;font-size:1.3rem;text-align:center">'
            f'TP&nbsp;{r["tp"]}</td>'
            f'<td style="padding:12px;background:#2d1a00;color:#f0a500;font-weight:700;font-size:1.3rem;text-align:center">'
            f'FP&nbsp;{r["fp"]}</td></tr>'
            f'<tr><th style="padding:8px;background:#161b22;color:#8b949e">Not flagged</th>'
            f'<td style="padding:12px;background:#2d0a0a;color:#f85149;font-weight:700;font-size:1.3rem;text-align:center">'
            f'FN&nbsp;{r["fn"]}</td>'
            f'<td style="padding:12px;background:#161b22;color:#57606a;font-weight:700;font-size:1.3rem;text-align:center">'
            f'TN&nbsp;{r["tn"]}</td></tr>'
            '</table>'
        )
        st.markdown(cm_html, unsafe_allow_html=True)

    with col_legend:
        st.markdown("**What each result means**")
        st.markdown(
            "- 🟢 **TP** - Radar flagged it *and* it actually broke → the tool earned its keep\n"
            "- 🟡 **FP** - Radar flagged it but it didn't break in 0.7.0 → still future-relevant "
            "  (BaseSamplerV1 / BaseEstimatorV1 will break in Qiskit 3.0)\n"
            "- 🔴 **FN** - Radar missed it → `TorchRuntimeClient` & `distribution_learners` "
            "  are module-level removals not caught by symbol-name scanning\n"
            "- ⚫ **TN** - Correctly not flagged"
        )
        st.markdown(
            f'<div style="margin-top:14px;padding:10px 14px;background:#f0fff4;'
            f'border-radius:6px;border-left:3px solid #3fb950;font-size:0.85rem">'
            f'<strong>Lead time</strong>: Radar would have alerted developers '
            f'<strong>{r["avg_lead_days"]} days ({r["avg_lead_months"]} months) '
            f'before the 0.7.0 release</strong> - enough time to migrate before the breakage.'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.divider()

    # ── Per-symbol prediction table ───────────────────────────────────────────
    st.markdown("**Per-symbol prediction breakdown**")

    RESULT_STYLE = {
        "TP": ("✅ TP", "#3fb950"),
        "FP": ("🟡 FP", "#f0a500"),
        "FN": ("🔴 FN", "#f85149"),
        "TN": ("⚫ TN", "#57606a"),
    }

    import pandas as pd
    bt_rows = []
    for p in r["predictions"]:
        label, color = RESULT_STYLE.get(p["result"], ("?", "#ccc"))
        bt_rows.append({
            "Symbol":          p["symbol"],
            "Result":          p["result"],
            "Days to break":   p["days_left_at_scan"],
            "Severity":        p["severity_predicted"].upper(),
            "Deprecated in":   p["deprecated_in"],
            "Replacement":     p["replacement"][:35],
            "Radar detected":  "✔" if p["radar_detected"] else "✘",
            "Actually broke":  "✔" if p["actually_broke"] else "✘",
        })

    st.dataframe(
        pd.DataFrame(bt_rows),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Days to break": st.column_config.NumberColumn("Days to break"),
        },
    )

    # ── Methodology note ─────────────────────────────────────────────────────
    with st.expander("📐  Methodology"):
        st.markdown(f"""
**Snapshot**: qiskit-machine-learning **{r['snapshot']}** (released {r['snapshot_date']})
- the codebase state Expiry Radar is simulated against.

**Ground truth**: All symbols officially removed in **{r['evaluated_against']}**
(released {r['evaluation_date']}) per the GitHub release notes.

**Detection model**: Expiry Radar scans for symbol names from the deprecation catalog
in Python source files using regex import/usage patterns.

**Known gap (FN)**: Module-level package removals (`TorchRuntimeClient`,
`distribution_learners`) are not caught because there are no matching import
statements in the surviving 1.0.0 codebase - they were fully removed before
the current snapshot. A future improvement would scan historical import graphs.

**FP note**: `BaseSamplerV1` and `BaseEstimatorV1` are flagged as FP against
the 0.7.0 ground truth because they were deprecated *later* (qiskit 1.2, 2024).
They are genuine future breakages - not false positives in practice.

**Metrics computed**:
- Precision = TP / (TP + FP) = {r['tp']} / {r['tp']+r['fp']} = **{r['precision']:.1%}**
- Recall    = TP / (TP + FN) = {r['tp']} / {r['tp']+r['fn']} = **{r['recall']:.1%}**
- F1        = 2·P·R / (P+R) = **{r['f1']:.2f}**
- Lead time = average days from scan to actual removal = **{r['avg_lead_days']} days**
        """)
