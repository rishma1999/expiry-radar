"""
score.py — Expiry Radar unified scorer
----------------------------------------
Merges findings from all collectors:
    eol_findings.json          — end-of-life dependencies
    deprecation_findings.json  — deprecated Qiskit/IBM symbols
    issue_findings.json        — stale workarounds for closed GitHub issues
    todo_findings.json         — hardcoded dates / TODOs (may be empty)

Scoring formula
---------------
urgency_score = (1 / max(days_left, 1)) * severity_weight * confidence

Severity weights  (aligned with severity-guide.md):
    critical → 4    (≤ 30 days)
    high     → 3    (≤ 90 days)
    medium   → 2    (≤ 180 days)
    low      → 1    (> 180 days)

For workaround findings (no days_left), urgency_score = days_since_closed / 365
scaled by severity weight.

Outputs
-------
    scored_findings.json  — merged list, sorted by urgency_score descending,
                            each entry augmented with `urgency_score` and `rank`.
"""

import datetime
import json
import math
import os

SEVERITY_WEIGHT = {"critical": 4, "high": 3, "medium": 2, "low": 1}

FINDING_SOURCES = [
    "eol_findings.json",
    "deprecation_findings.json",
    "issue_findings.json",
    "todo_findings.json",
]


def _load_all() -> list[dict]:
    findings: list[dict] = []
    for path in FINDING_SOURCES:
        if not os.path.exists(path):
            continue
        with open(path) as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                print(f"[score] Warning: could not parse {path} — skipping.")
                continue
        if isinstance(data, list):
            findings.extend(data)
    return findings


def _urgency(finding: dict) -> float:
    sev = finding.get("severity", "low")
    weight = SEVERITY_WEIGHT.get(sev, 1)
    confidence = float(finding.get("confidence", 0.8))
    days_left = finding.get("days_left")

    if days_left is not None:
        # Negative days_left = already past deadline → treat as maximally urgent
        effective_days = max(int(days_left), 1) if days_left > 0 else 1
        raw = (1 / effective_days) * weight * confidence
    else:
        # Workaround findings: use days_since_closed as a staleness proxy
        ev = finding.get("evidence", {})
        days_stale = ev.get("days_since_closed", 0) or 0
        # Normalise: 1 year stale → 1.0 base, scaled by weight and confidence
        raw = (days_stale / 365) * weight * confidence

    return round(raw, 6)


def score(findings: list[dict]) -> list[dict]:
    for f in findings:
        f["urgency_score"] = _urgency(f)

    # Sort: highest urgency first; break ties by severity weight desc, then id
    findings.sort(
        key=lambda f: (
            -f["urgency_score"],
            -SEVERITY_WEIGHT.get(f.get("severity", "low"), 1),
            f.get("id", ""),
        )
    )

    for rank, f in enumerate(findings, 1):
        f["rank"] = rank

    return findings


def main() -> None:
    print("[score] Loading findings from all collectors …")
    findings = _load_all()
    print(f"[score] Loaded {len(findings)} total findings.")

    if not findings:
        print("[score] Nothing to score.")
        return

    scored = score(findings)

    with open("scored_findings.json", "w") as f:
        json.dump(scored, f, indent=2)

    print(f"[score] Written {len(scored)} ranked findings → scored_findings.json\n")
    print(f"  {'rank':<4}  {'id':<8}  {'score':>8}  {'sev':<8}  title")
    print(f"  {'-'*4}  {'-'*8}  {'-'*8}  {'-'*8}  -----")
    for f in scored:
        print(
            f"  {f['rank']:<4}  {f['id']:<8}  "
            f"{f['urgency_score']:>8.4f}  {f.get('severity','?'):<8}  "
            f"{f.get('title','')[:60]}"
        )


if __name__ == "__main__":
    main()
