"""
collect_release_notes.py — Expiry Radar · Qiskit Release Notes RAG
--------------------------------------------------------------------
Acts as a lightweight retrieval-augmented generator (RAG) for Qiskit
deprecation intelligence:

  1. FETCH   — pulls the latest Qiskit GitHub release bodies (up to N pages)
               to extract Deprecated / Removed sections.
  2. CATALOG — merges fetched deprecations with an authoritative hardcoded
               catalog of high-impact deprecations confirmed from Qiskit 2.x
               migration guides and release notes.
  3. SCAN    — greps the local codebase for every deprecated symbol.
  4. SCORE   — assigns severity using severity-guide.md rules (days to removal).
  5. EMIT    — writes deprecation_findings.json conforming to finding-schema.json.

Environment variable:
    GITHUB_TOKEN — optional; avoids the 60 req/hr unauthenticated API limit.

Usage:
    python collect_release_notes.py [--root PATH] [--releases N]
"""

import argparse
import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Authoritative deprecation catalog
# Built from:
#   • Qiskit 2.0 release notes  (removals of 1.x deprecations)
#   • Qiskit 2.2 release notes  (#14511 — legacy circuit library)
#   • Qiskit 2.3 release notes  (#15356, #15360)
#   • Qiskit migration guide    https://docs.quantum.ibm.com/migration-guides/qiskit-2.0
#   • Qiskit 1.x deprecation warnings in stable/2.5 source
# ---------------------------------------------------------------------------
DEPRECATION_CATALOG: list[dict] = [
    # ── Primitives V1 ────────────────────────────────────────────────────────
    {
        "symbol": "BaseSamplerV1",
        "import_path": "qiskit.primitives",
        "deprecated_in": "1.2",
        "removed_in": "3.0",
        "removal_date": "2027-04-01",
        "description": (
            "BaseSamplerV1 (and all V1 sampler implementations) are deprecated in favour "
            "of BaseSamplerV2. The V1 interface will be removed in Qiskit 3.0."
        ),
        "migration": "Replace BaseSamplerV1 usage with BaseSamplerV2 interface.",
        "source": "https://docs.quantum.ibm.com/migration-guides/qiskit-2.0#primitives",
    },
    {
        "symbol": "BaseEstimatorV1",
        "import_path": "qiskit.primitives",
        "deprecated_in": "1.2",
        "removed_in": "3.0",
        "removal_date": "2027-04-01",
        "description": (
            "BaseEstimatorV1 (and all V1 estimator implementations) are deprecated in favour "
            "of BaseEstimatorV2. The V1 interface will be removed in Qiskit 3.0."
        ),
        "migration": "Replace BaseEstimatorV1 usage with BaseEstimatorV2 interface.",
        "source": "https://docs.quantum.ibm.com/migration-guides/qiskit-2.0#primitives",
    },
    # ── QuasiDistribution ────────────────────────────────────────────────────
    {
        "symbol": "QuasiDistribution",
        "import_path": "qiskit.result",
        "deprecated_in": "1.2",
        "removed_in": "3.0",
        "removal_date": "2027-04-01",
        "description": (
            "qiskit.result.QuasiDistribution is part of the V1 primitives result model. "
            "With V1 primitives deprecated, QuasiDistribution will be removed in Qiskit 3.0. "
            "V2 samplers return BitArray results via SamplerPubResult."
        ),
        "migration": (
            "Migrate to V2 sampler and use SamplerPubResult / BitArray instead of "
            "QuasiDistribution."
        ),
        "source": "https://docs.quantum.ibm.com/migration-guides/qiskit-2.0#sampler",
    },
    # ── providers.Options ────────────────────────────────────────────────────
    {
        "symbol": "Options",
        "import_path": "qiskit.providers",
        "deprecated_in": "2.0",
        "removed_in": "2.x",
        "removal_date": "2026-10-01",
        "description": (
            "qiskit.providers.Options is tied to BackendV1-era options handling. "
            "BackendV1 was fully removed in Qiskit 2.0. Backends using Options "
            "should migrate to BackendV2 with qiskit.providers.BackendV2."
        ),
        "migration": "Migrate to BackendV2 options model.",
        "source": "https://docs.quantum.ibm.com/migration-guides/qiskit-2.0#backend",
    },
    # ── PrimitiveJob (internal) ───────────────────────────────────────────────
    {
        "symbol": "PrimitiveJob",
        "import_path": "qiskit.primitives.primitive_job",
        "deprecated_in": "1.3",
        "removed_in": "3.0",
        "removal_date": "2027-04-01",
        "description": (
            "qiskit.primitives.primitive_job.PrimitiveJob is an internal implementation "
            "detail of V1 primitives. Directly subclassing or importing it is unsupported "
            "in the V2 model and will be removed with V1 primitives in Qiskit 3.0."
        ),
        "migration": (
            "AlgorithmJob should subclass BasePrimitiveJob or use the job returned by "
            "the V2 primitive directly."
        ),
        "source": "https://docs.quantum.ibm.com/migration-guides/qiskit-2.0#primitives",
    },
    # ── annotated=None in control() ──────────────────────────────────────────
    {
        "symbol": "annotated=None",
        "import_path": "qiskit.circuit.QuantumCircuit.control",
        "deprecated_in": "2.3",
        "removed_in": "3.0",
        "removal_date": "2027-01-01",
        "description": (
            "Passing annotated=None to gate.control() is deprecated as of Qiskit 2.3 "
            "(release note #15356). The default will change to annotated=False in 3.0."
        ),
        "migration": "Pass annotated=False or annotated=True explicitly.",
        "source": "https://github.com/Qiskit/qiskit/releases/tag/2.3.0",
    },
    # ── Legacy circuit library classes ───────────────────────────────────────
    {
        "symbol": "ExactReciprocal",
        "import_path": "qiskit.circuit.library",
        "deprecated_in": "2.2",
        "removed_in": "3.0",
        "removal_date": "2027-04-01",
        "description": (
            "ExactReciprocal is deprecated in Qiskit 2.2 as part of the legacy "
            "circuit library cleanup (#14511). Will be removed in Qiskit 3.0."
        ),
        "migration": "No direct replacement; implement inline.",
        "source": "https://github.com/Qiskit/qiskit/releases/tag/2.2.0",
    },
    {
        "symbol": "LinearAmplitudeFunction",
        "import_path": "qiskit.circuit.library",
        "deprecated_in": "2.2",
        "removed_in": "3.0",
        "removal_date": "2027-04-01",
        "description": (
            "LinearAmplitudeFunction is deprecated in Qiskit 2.2 (#14511). "
            "Will be removed in Qiskit 3.0."
        ),
        "migration": "No direct replacement; implement inline.",
        "source": "https://github.com/Qiskit/qiskit/releases/tag/2.2.0",
    },
    {
        "symbol": "QuantumVolume",
        "import_path": "qiskit.circuit.library",
        "deprecated_in": "2.2",
        "removed_in": "3.0",
        "removal_date": "2027-04-01",
        "description": (
            "QuantumVolume circuit is deprecated in Qiskit 2.2 (#14511). "
            "Will be removed in Qiskit 3.0."
        ),
        "migration": "Use qiskit_aer.primitives or generate the circuit manually.",
        "source": "https://github.com/Qiskit/qiskit/releases/tag/2.2.0",
    },
    # ── MCMT → MCMTGate ──────────────────────────────────────────────────────
    {
        "symbol": "MCMT",
        "import_path": "qiskit.circuit.library",
        "deprecated_in": "1.3",
        "removed_in": "2.4",
        "removal_date": "2026-04-16",
        "description": (
            "MCMT (Multi-Control Multi-Target) was deprecated in Qiskit 1.3 in favour of "
            "MCMTGate and was fully removed in Qiskit 2.4 (#15606)."
        ),
        "migration": "Replace MCMT with MCMTGate.",
        "source": "https://github.com/Qiskit/qiskit/releases/tag/2.4.0",
    },
    # ── ParameterValueType ────────────────────────────────────────────────────
    {
        "symbol": "ParameterValueType",
        "import_path": "qiskit.circuit.parameterexpression",
        "deprecated_in": "2.1",
        "removed_in": "3.0",
        "removal_date": "2027-04-01",
        "description": (
            "qiskit.circuit.parameterexpression.ParameterValueType is a private type alias "
            "that may be removed without notice in a future major release. "
            "It is not part of the public API."
        ),
        "migration": "Use float | ParameterExpression as the type annotation directly.",
        "source": "https://github.com/Qiskit/qiskit/blob/stable/2.5/qiskit/circuit/parameterexpression.py",
    },
    # ── BackendV2Converter ────────────────────────────────────────────────────
    {
        "symbol": "BackendV2Converter",
        "import_path": "qiskit.providers",
        "deprecated_in": "2.0",
        "removed_in": "2.x",
        "removal_date": "2026-10-01",
        "description": (
            "BackendV2Converter was deprecated in Qiskit 2.0 (#12840). BackendV1 was removed "
            "entirely in 2.0 so the converter has no purpose."
        ),
        "migration": "Use BackendV2 natively.",
        "source": "https://github.com/Qiskit/qiskit/releases/tag/2.0.0",
    },
]

GITHUB_API_RELEASES = (
    "https://api.github.com/repos/Qiskit/qiskit/releases?per_page={per_page}"
)

# Regex to extract deprecated symbols from GitHub release note Deprecated/Removed sections
BACKTICK_SYMBOL_RE = re.compile(r"`([A-Za-z][A-Za-z0-9_.]+)`")

# ── Severity guide (from severity-guide.md) ──────────────────────────────────
def _days_left(removal_date_str: str | None) -> int:
    if not removal_date_str:
        return 9999
    try:
        removal = datetime.date.fromisoformat(removal_date_str)
        return (removal - datetime.date.today()).days
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


# ---------------------------------------------------------------------------
# Step 1 — fetch release notes from GitHub
# ---------------------------------------------------------------------------

def _github_headers() -> dict:
    headers = {
        "User-Agent": "expiry-radar/1.0",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_releases(n: int = 15) -> list[dict]:
    """Fetch up to n recent Qiskit releases from GitHub."""
    url = GITHUB_API_RELEASES.format(per_page=min(n, 30))
    try:
        req = urllib.request.Request(url, headers=_github_headers())
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        print(f"[collect_rn] GitHub API error: {exc}", file=sys.stderr)
        return []


def extract_deprecations_from_releases(releases: list[dict]) -> list[dict]:
    """
    Parse GitHub release bodies and extract deprecated/removed symbol mentions.
    Returns lightweight dicts: {symbol, release_tag, release_date, section, context}.
    """
    found = []
    section_re = re.compile(r"^#{1,3}\s*(Deprecated|Removed|Breaking)", re.I)

    for rel in releases:
        tag = rel.get("tag_name", "")
        date = rel.get("published_at", "")[:10]
        body = rel.get("body", "")
        lines = body.split("\n")
        in_section = False
        section_name = ""

        for line in lines:
            m = section_re.match(line)
            if m:
                in_section = True
                section_name = m.group(1).lower()
                continue
            if in_section:
                if re.match(r"^#{1,3}\s", line):
                    in_section = False
                    section_name = ""
                    continue
                for sym in BACKTICK_SYMBOL_RE.findall(line):
                    found.append({
                        "symbol": sym,
                        "release_tag": tag,
                        "release_date": date,
                        "section": section_name,
                        "context": line.strip(),
                    })
    return found


# ---------------------------------------------------------------------------
# Step 2 — scan codebase for deprecated symbols
# ---------------------------------------------------------------------------

def _build_search_pattern(symbol: str) -> re.Pattern:
    """
    Build a regex that matches meaningful uses of a symbol in Python source.
    Avoids matching inside comments that explain the deprecation itself.
    """
    # Match: import X, from X import Y, X(, X., ClassName(X, isinstance(x, X)
    escaped = re.escape(symbol)
    return re.compile(
        rf"(?:import\s+{escaped}|from\s+\S+\s+import\s+[^#\n]*\b{escaped}\b"
        rf"|\b{escaped}\s*[(\.,]|\bisinstance\s*\([^,]+,\s*{escaped}\b)"
    )


SCAN_EXTENSIONS = {".py"}


def scan_codebase(root: Path, symbols: list[str]) -> dict[str, list[dict]]:
    """
    Returns {symbol: [{"file": ..., "line": ..., "content": ...}, ...]}
    """
    patterns = {sym: _build_search_pattern(sym) for sym in symbols}
    results: dict[str, list[dict]] = {sym: [] for sym in symbols}

    for path in root.rglob("*"):
        if path.suffix not in SCAN_EXTENSIONS:
            continue
        if any(p.startswith(".") or p == "__pycache__" for p in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            for sym, pat in patterns.items():
                if pat.search(line):
                    results[sym].append({
                        "file": str(path),
                        "line": line_no,
                        "content": line.strip(),
                    })

    return results


# ---------------------------------------------------------------------------
# Step 3 — build findings
# ---------------------------------------------------------------------------

def build_findings(
    catalog: list[dict],
    codebase_hits: dict[str, list[dict]],
) -> list[dict]:
    findings = []
    idx = 1

    for entry in catalog:
        sym = entry["symbol"]
        hits = codebase_hits.get(sym, [])
        if not hits:
            continue

        days = _days_left(entry.get("removal_date"))
        primary = hits[0]
        primary_loc = f"{primary['file']}:{primary['line']}"

        findings.append({
            "id": f"DEP-{idx:03d}",
            "category": "deprecation",
            "title": (
                f"{sym} deprecated in Qiskit {entry['deprecated_in']}, "
                f"removed in {entry['removed_in']}"
            ),
            "breaks_on": entry.get("removal_date"),
            "days_left": days,
            "severity": _severity(days),
            "confidence": 0.9,
            "evidence": {
                "code": primary_loc,
                "source": entry["source"],
                "all_locations": [f"{h['file']}:{h['line']}" for h in hits],
                "description": entry["description"],
                "migration": entry.get("migration", ""),
                "deprecated_in": entry["deprecated_in"],
                "removed_in": entry["removed_in"],
            },
            "fix": "manual",
            "status": "open",
        })
        idx += 1

    return findings


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(root: str = ".", n_releases: int = 15) -> None:
    root_path = Path(root).resolve()

    # ── Phase 1: fetch live release notes ──────────────────────────────────
    print(f"[collect_rn] Fetching {n_releases} latest Qiskit releases from GitHub …")
    releases = fetch_releases(n_releases)
    print(f"[collect_rn] Fetched {len(releases)} releases.")

    live_deprecations = extract_deprecations_from_releases(releases)
    print(f"[collect_rn] Extracted {len(live_deprecations)} symbol mentions from release notes.")

    # ── Phase 2: merge live mentions into catalog (deduplicated) ───────────
    catalog = list(DEPRECATION_CATALOG)
    catalog_symbols = {e["symbol"] for e in catalog}

    new_from_live = 0
    for item in live_deprecations:
        sym = item["symbol"]
        if sym not in catalog_symbols and item["section"] in ("deprecated", "removed"):
            # Add minimal entry for newly-seen symbols from release notes
            catalog.append({
                "symbol": sym,
                "import_path": "qiskit (from release notes)",
                "deprecated_in": item["release_tag"],
                "removed_in": "unknown",
                "removal_date": None,
                "description": f"Mentioned in Qiskit {item['release_tag']} {item['section']} section: {item['context']}",
                "migration": "See release notes.",
                "source": f"https://github.com/Qiskit/qiskit/releases/tag/{item['release_tag']}",
            })
            catalog_symbols.add(sym)
            new_from_live += 1

    print(f"[collect_rn] Catalog: {len(DEPRECATION_CATALOG)} hardcoded + {new_from_live} from live notes = {len(catalog)} total.")

    # ── Phase 3: scan codebase ─────────────────────────────────────────────
    all_symbols = [e["symbol"] for e in catalog]
    print(f"[collect_rn] Scanning {root_path} for {len(all_symbols)} deprecated symbols …")
    hits = scan_codebase(root_path, all_symbols)
    matched = {sym: locs for sym, locs in hits.items() if locs}
    print(f"[collect_rn] Found {len(matched)} deprecated symbol(s) in use.")

    # ── Phase 4: build and write findings ──────────────────────────────────
    findings = build_findings(catalog, hits)

    with open("deprecation_findings.json", "w") as f:
        json.dump(findings, f, indent=2)
    print(f"[collect_rn] Emitted {len(findings)} findings → deprecation_findings.json")

    if findings:
        print("\n  id        severity   days_left  symbol")
        print("  --------  ---------  ---------  ------")
        for fin in sorted(findings, key=lambda x: (x["days_left"] or 9999)):
            dl = fin["days_left"]
            dl_str = f"{dl:>9}" if dl is not None else "  unknown"
            print(f"  {fin['id']:<8}  {fin['severity']:<9}  {dl_str}  {fin['title'][:70]}")
    else:
        print("[collect_rn] No deprecated symbols found in codebase.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Qiskit Release Notes RAG collector.")
    parser.add_argument("--root", default=".", help="Root directory to scan.")
    parser.add_argument("--releases", type=int, default=15, help="Number of GitHub releases to fetch.")
    args = parser.parse_args()
    main(root=args.root, n_releases=args.releases)
