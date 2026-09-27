"""
app.py — Expiry Radar · Streamlit Dashboard
---------------------------------------------
Run:  streamlit run app.py
"""

import json
import os
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
        pct = 60  # workaround — no deadline, show as orange-level
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

    trace_slot : st.empty() — receives the growing step checklist
    log_slot   : st.empty() — receives the raw stdout log accordion
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
        width=80,
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
    st.markdown("## 🤖 Agentic Pipeline — Live Trace")
    st.caption(
        "Each subagent runs sequentially. Watch the tick marks as each collector "
        "completes and hands off to the next."
    )

    trace_slot = st.empty()
    log_slot   = st.empty()

    ok = run_pipeline_streaming(trace_slot, log_slot)

    if ok:
        st.success("✅  All agents completed. Findings refreshed — scroll down to see results.")
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

tab_timeline, tab_calendar, tab_table, tab_detail = st.tabs([
    "⏱  Timeline", "📅  Calendar", "📋  All Findings", "🔍  Detail"
])

# ─────────────────────────────────────────────────────────────────────────────
# TAB 1 — Timeline (horizontal urgency bars sorted by rank)
# ─────────────────────────────────────────────────────────────────────────────

with tab_timeline:
    st.markdown("### Breaking Changes Timeline")
    st.caption(
        "Bars show urgency — longer/redder = closer to deadline. "
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
        breaks  = f.get("breaks_on", "—")
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
# TAB 2 — Calendar (month-grouped list of upcoming breaks)
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
                f'<span style="color:#57606a;font-size:0.85rem">— {len(items)} finding(s)</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

            for f in items:
                sev   = f.get("severity", "unknown")
                icon  = CAT_ICON.get(f.get("category", ""), "•")
                dl    = f.get("days_left")
                dl_s  = f"{dl}d" if dl is not None else "?"
                st.markdown(
                    f"&nbsp;&nbsp;{_badge(sev)} {icon} **{f['id']}** — "
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
                f'<span style="color:#57606a;font-size:0.85rem">— {len(past)} finding(s) already overdue</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
            for f in past:
                sev  = f.get("severity", "unknown")
                icon = CAT_ICON.get(f.get("category", ""), "•")
                st.markdown(
                    f"&nbsp;&nbsp;{_badge(sev)} {icon} **{f['id']}** — "
                    f"{f.get('title','?')} *(broke on {f.get('breaks_on','?')})*",
                    unsafe_allow_html=True,
                )

# ─────────────────────────────────────────────────────────────────────────────
# TAB 3 — All Findings table
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
            "Breaks On": f.get("breaks_on") or "—",
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
# TAB 4 — Detail drilldown
# ─────────────────────────────────────────────────────────────────────────────

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
            f'<strong style="font-size:1.1rem">{f.get("id")} — {f.get("title")}</strong>'
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
            st.markdown(f"- **Breaks on:** {f.get('breaks_on') or '—'}")
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
