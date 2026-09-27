"""
collect_eol.py — Expiry Radar EOL collector
--------------------------------------------
1. Reads requirements.txt and writes eol_candidates.json  (unchanged contract).
2. For every candidate, tries endoflife.date API for real EOL date.
3. Falls back to a hardcoded IBM/Qiskit version map for packages the API
   doesn't track.
4. Merges everything and emits eol_findings.json, each entry matching
   the project's finding-schema.json.
"""

import json
import re
import sys
import datetime
import urllib.request
import urllib.error

# ---------------------------------------------------------------------------
# Hardcoded IBM / Qiskit EOL map
# Keys are lower-cased PyPI package names. Values are ISO date strings.
# Sources:
#   https://github.com/Qiskit/qiskit/blob/main/DEPRECATIONS.md
#   https://ibm.github.io/qiskit-ibm-runtime/release_schedule.html
# ---------------------------------------------------------------------------
HARDCODED_EOL: dict[str, dict] = {
    # Qiskit Terra was superseded by qiskit 1.x; 0.x EOL 2024-06-01
    "qiskit-terra": {
        "eol": "2024-06-01",
        "latest": "0.46.0",
        "link": "https://github.com/Qiskit/qiskit/blob/main/DEPRECATIONS.md",
    },
    # qiskit 0.x series EOL alongside terra
    "qiskit": {
        "eol": "2025-04-01",
        "latest": "1.4.2",
        "link": "https://github.com/Qiskit/qiskit/blob/main/DEPRECATIONS.md",
    },
    # Qiskit IBM Runtime — current supported release schedule
    "qiskit-ibm-runtime": {
        "eol": "2026-01-01",
        "latest": "0.30.0",
        "link": "https://ibm.github.io/qiskit-ibm-runtime/release_schedule.html",
    },
    # Qiskit Aer 0.x EOL with qiskit-terra
    "qiskit-aer": {
        "eol": "2024-06-01",
        "latest": "0.13.3",
        "link": "https://github.com/Qiskit/qiskit-aer",
    },
    # IBM quantum-computing SDK (legacy)
    "quantum-computing": {
        "eol": "2024-12-31",
        "latest": "1.0.0",
        "link": "https://github.com/IBM/quantum-computing",
    },
    # cryptography: tracks OpenSSL lifecycle; flag old majors
    "cryptography": {
        "eol": "2026-10-01",
        "latest": "42.0.8",
        "link": "https://cryptography.io/en/latest/changelog/",
    },
    # pydantic v1 EOL (v2 is current)
    "pydantic": {
        "eol": "2024-06-30",
        "latest": "2.7.4",
        "link": "https://docs.pydantic.dev/latest/migration/",
    },
}

EOL_DATE_API = "https://endoflife.date/api/{product}.json"

# endoflife.date product slugs differ from PyPI names for some packages
PYPI_TO_EOL_SLUG: dict[str, str] = {
    "requests": "python-requests",
    "streamlit": "streamlit",
    "packaging": None,   # not tracked on endoflife.date
    "rank_bm25": None,
    "pydantic": "pydantic",
    "cryptography": None,   # use hardcoded map
}


def _parse_version(dep_str: str) -> tuple[str, str | None]:
    """Split 'package==1.2.3' or 'package>=1.0' into (name, version|None)."""
    m = re.match(r"([A-Za-z0-9_.\-]+)\s*[><=!~]+\s*([0-9][^\s,;]*)", dep_str)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    # bare name, no version pin
    return dep_str.split("[")[0].strip(), None


def _fetch_eol_api(slug: str) -> list[dict]:
    """Return parsed JSON from endoflife.date for a given slug, or []."""
    url = EOL_DATE_API.format(product=slug)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "expiry-radar/1.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError):
        return []


def _best_cycle(cycles: list[dict], pinned_version: str | None) -> dict | None:
    """
    Pick the most relevant release cycle from endoflife.date response.
    If a version is pinned, prefer the cycle that matches its major.minor.
    Otherwise return the first non-EOL cycle (or the first cycle at all).
    """
    if not cycles:
        return None

    if pinned_version:
        major_minor = ".".join(pinned_version.split(".")[:2])
        for cycle in cycles:
            cycle_name = str(cycle.get("cycle", ""))
            if cycle_name == major_minor or cycle_name.startswith(major_minor + "."):
                return cycle

    # Fallback: latest cycle (first entry) — endoflife.date lists newest first
    return cycles[0]


def _days_left(eol_date_str: str) -> int:
    try:
        eol = datetime.date.fromisoformat(eol_date_str)
        return (eol - datetime.date.today()).days
    except ValueError:
        return 9999


def _severity(days: int) -> str:
    if days <= 30:
        return "critical"
    if days <= 90:
        return "high"
    if days <= 180:
        return "medium"
    return "low"


def _make_finding(pkg_name: str, version: str | None, source: str,
                  eol_date: str, evidence_link: str, index: int) -> dict:
    days = _days_left(eol_date)
    ver_tag = f" {version}" if version else ""
    return {
        "id": f"EOL-{index:03d}",
        "category": "eol",
        "title": f"{pkg_name}{ver_tag} reaches end-of-life",
        "breaks_on": eol_date,
        "days_left": days,
        "severity": _severity(days),
        "confidence": 0.85,
        "evidence": {
            "code": source,
            "source": evidence_link,
        },
        "fix": "manual",
        "status": "open",
    }


# ---------------------------------------------------------------------------
# Step 1 — collect candidates (unchanged contract with the rest of the pipeline)
# ---------------------------------------------------------------------------
def collect_candidates(req_file: str = "requirements.txt") -> list[dict]:
    deps = []
    try:
        with open(req_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    deps.append({"dependency": line, "source": req_file})
    except FileNotFoundError:
        print(f"[collect_eol] {req_file} not found — skipping.", file=sys.stderr)
    return deps


# ---------------------------------------------------------------------------
# Step 2 — enrich with EOL dates
# ---------------------------------------------------------------------------
def enrich(candidates: list[dict]) -> list[dict]:
    findings: list[dict] = []
    idx = 1

    for entry in candidates:
        raw = entry["dependency"]
        source = entry.get("source", "requirements.txt")
        pkg_name, version = _parse_version(raw)
        pkg_lower = pkg_name.lower()

        eol_date: str | None = None
        evidence_link: str = "https://endoflife.date"

        # -- Layer 1: live API -------------------------------------------
        slug = PYPI_TO_EOL_SLUG.get(pkg_lower)
        if slug is None and pkg_lower not in HARDCODED_EOL:
            # Try the package name directly as slug
            slug = pkg_lower

        if slug:
            cycles = _fetch_eol_api(slug)
            cycle = _best_cycle(cycles, version)
            if cycle:
                raw_eol = cycle.get("eol") or cycle.get("endOfLife")
                if isinstance(raw_eol, str) and re.match(r"\d{4}-\d{2}-\d{2}", raw_eol):
                    eol_date = raw_eol
                    evidence_link = f"https://endoflife.date/{slug}"
                elif isinstance(raw_eol, bool) and raw_eol:
                    # already EOL, no specific date; treat as yesterday
                    eol_date = str(datetime.date.today() - datetime.timedelta(days=1))
                    evidence_link = f"https://endoflife.date/{slug}"

        # -- Layer 2: hardcoded fallback ---------------------------------
        if eol_date is None and pkg_lower in HARDCODED_EOL:
            meta = HARDCODED_EOL[pkg_lower]
            eol_date = meta["eol"]
            evidence_link = meta.get("link", evidence_link)

        # -- Layer 3: skip if no EOL date could be determined -----------
        if eol_date is None:
            print(f"[collect_eol] No EOL data for '{pkg_name}' — skipping.")
            continue

        findings.append(
            _make_finding(pkg_name, version, source, eol_date, evidence_link, idx)
        )
        idx += 1

    return findings


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    # Phase 1 — produce eol_candidates.json (unchanged downstream contract)
    candidates = collect_candidates()
    with open("eol_candidates.json", "w") as f:
        json.dump(candidates, f, indent=2)
    print(f"[collect_eol] Found {len(candidates)} dependencies to check.")

    # Phase 2 — enrich and emit eol_findings.json
    print("[collect_eol] Querying endoflife.date API + hardcoded fallback map …")
    findings = enrich(candidates)

    with open("eol_findings.json", "w") as f:
        json.dump(findings, f, indent=2)

    print(f"[collect_eol] Emitted {len(findings)} EOL findings → eol_findings.json")

    # Surface a summary
    if findings:
        print("\n  id        severity   days_left  package")
        print("  --------  ---------  ---------  -------")
        for fin in sorted(findings, key=lambda x: x["days_left"]):
            print(f"  {fin['id']:<8}  {fin['severity']:<9}  {fin['days_left']:>9}  {fin['title']}")


if __name__ == "__main__":
    main()
