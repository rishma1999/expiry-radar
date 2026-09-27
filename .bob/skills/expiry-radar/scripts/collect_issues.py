"""
collect_issues.py - Expiry Radar GitHub issue collector
---------------------------------------------------------
Scans all Python, Markdown, and RST files in the target codebase for
GitHub issue URLs embedded in code comments, docstrings, and inline
workaround markers.

For every unique issue URL found it:
  1. Calls the GitHub REST API to get the current issue state.
  2. Classifies whether the reference looks like a live workaround
     (comment contains workaround/hack/todo/skip/disable keywords)
     or is a passive reference (regression test, changelog mention).
  3. Flags CLOSED issues that still have an active workaround in code.
  4. Writes issue_candidates.json with every reference, and
     issue_findings.json with only the flagged findings in finding-schema.json
     format, ready for the Expiry Radar scoring pipeline.

Environment variable:
    GITHUB_TOKEN - optional; set to avoid GitHub API rate-limits (60 req/hr
                   unauthenticated vs 5 000 req/hr authenticated).

Usage:
    python collect_issues.py [--root PATH]   (default: cwd)
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
# Config
# ---------------------------------------------------------------------------

# File extensions to scan
SCAN_EXTENSIONS = {".py", ".md", ".rst", ".txt"}

# Regex: capture full GitHub issue / PR URLs
ISSUE_URL_RE = re.compile(
    r"https://github\.com/(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+)"
    r"/(?:issues|pull)/(?P<number>\d+)",
    re.IGNORECASE,
)

# Keywords that suggest the surrounding line is a live workaround, not just
# a passive reference (regression note, changelog, URL-in-string, etc.)
WORKAROUND_KEYWORDS = re.compile(
    r"\b(workaround|work.around|hack|todo|fixme|skip|disable[sd]?|"
    r"temporary|temp[.\s]fix|pending|blocked.by|waiting.for|"
    r"until.*fixed|enable.*when.*fixed|mirrors?\s+issue|refer\s+to\s+issue|"
    r"this\s+would\s+give)\b",
    re.IGNORECASE,
)

GITHUB_API = "https://api.github.com/repos/{owner}/{repo}/issues/{number}"


# ---------------------------------------------------------------------------
# GitHub API helper
# ---------------------------------------------------------------------------

def _github_token() -> str | None:
    return os.environ.get("GITHUB_TOKEN")


def _fetch_issue(owner: str, repo: str, number: str) -> dict | None:
    """Return GitHub issue/PR JSON dict, or None on any error."""
    url = GITHUB_API.format(owner=owner, repo=repo, number=number)
    headers = {
        "User-Agent": "expiry-radar/1.0",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = _github_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {"state": "not_found", "title": "Not found", "number": number}
        if exc.code == 403:
            print(
                f"[collect_issues] Rate-limited by GitHub API. "
                f"Set GITHUB_TOKEN env var to increase the limit.",
                file=sys.stderr,
            )
            return None
        return None
    except (urllib.error.URLError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def _workaround_score(line: str) -> bool:
    """True if the line looks like an active workaround, not a passive mention."""
    return bool(WORKAROUND_KEYWORDS.search(line))


def scan_file(filepath: Path) -> list[dict]:
    """Return list of issue reference dicts found in a single file."""
    refs = []
    try:
        text = filepath.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return refs

    for line_no, line in enumerate(text.splitlines(), 1):
        for m in ISSUE_URL_RE.finditer(line):
            refs.append(
                {
                    "file": str(filepath),
                    "line": line_no,
                    "content": line.strip(),
                    "url": m.group(0),
                    "owner": m.group("owner"),
                    "repo": m.group("repo"),
                    "number": m.group("number"),
                    "is_workaround": _workaround_score(line),
                }
            )
    return refs


def scan_tree(root: Path) -> list[dict]:
    """Recursively scan all matching files under root."""
    refs = []
    for path in root.rglob("*"):
        if path.suffix.lower() in SCAN_EXTENSIONS and path.is_file():
            # Skip hidden dirs (.git, .bob, __pycache__)
            if any(part.startswith(".") or part == "__pycache__" for part in path.parts):
                continue
            refs.extend(scan_file(path))
    return refs


# ---------------------------------------------------------------------------
# Deduplication & API enrichment
# ---------------------------------------------------------------------------

def enrich(refs: list[dict]) -> list[dict]:
    """
    Attach GitHub state to each ref. Deduplicates API calls by issue URL.
    Returns the enriched list (all refs, not just flagged ones).
    """
    cache: dict[str, dict | None] = {}

    for ref in refs:
        key = ref["url"]
        if key not in cache:
            print(f"[collect_issues] Checking {key} …")
            cache[key] = _fetch_issue(ref["owner"], ref["repo"], ref["number"])

        issue = cache[key]
        if issue:
            ref["issue_state"] = issue.get("state", "unknown")
            ref["issue_title"] = issue.get("title", "")
            ref["issue_closed_at"] = issue.get("closed_at")
        else:
            ref["issue_state"] = "api_error"
            ref["issue_title"] = ""
            ref["issue_closed_at"] = None

    return refs


# ---------------------------------------------------------------------------
# Finding builder
# ---------------------------------------------------------------------------

def _days_since(iso_date: str | None) -> int:
    if not iso_date:
        return 0
    try:
        closed = datetime.date.fromisoformat(iso_date[:10])
        return (datetime.date.today() - closed).days
    except ValueError:
        return 0


def _severity(days_stale: int) -> str:
    """Severity based on how long a workaround has been stale."""
    if days_stale >= 365:
        return "high"
    if days_stale >= 90:
        return "medium"
    return "low"


def build_findings(refs: list[dict]) -> list[dict]:
    """
    Return only refs where:
      - issue is CLOSED  AND
      - the surrounding code looks like a live workaround
    Formatted as finding-schema.json objects.
    """
    findings = []
    idx = 1

    # Group refs by URL so we emit one finding per issue (referencing all locations)
    by_url: dict[str, list[dict]] = {}
    for ref in refs:
        if ref.get("issue_state") == "closed" and ref.get("is_workaround"):
            by_url.setdefault(ref["url"], []).append(ref)

    for url, group in by_url.items():
        first = group[0]
        days_stale = _days_since(first.get("issue_closed_at"))

        # Primary evidence location (first occurrence)
        primary_loc = f"{first['file']}:{first['line']}"

        findings.append(
            {
                "id": f"ISS-{idx:03d}",
                "category": "workaround",
                "title": (
                    f"Workaround for closed issue "
                    f"{first['owner']}/{first['repo']}#{first['number']}: "
                    f"{first['issue_title'][:60]}"
                ),
                "breaks_on": None,          # no hard deadline - upstream already fixed
                "days_left": None,
                "severity": _severity(days_stale),
                "confidence": 0.8,
                "evidence": {
                    "code": primary_loc,
                    "source": url,
                    "all_locations": [f"{r['file']}:{r['line']}" for r in group],
                    "days_since_closed": days_stale,
                    "issue_closed_at": first.get("issue_closed_at"),
                },
                "fix": "manual",
                "status": "open",
            }
        )
        idx += 1

    return findings


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(root: str = ".") -> None:
    root_path = Path(root).resolve()
    print(f"[collect_issues] Scanning {root_path} …")

    # Phase 1 - collect all issue references
    refs = scan_tree(root_path)
    print(f"[collect_issues] Found {len(refs)} issue URL reference(s) in code.")

    # Phase 2 - enrich with GitHub API
    refs = enrich(refs)

    # Write full candidate list
    with open("issue_candidates.json", "w") as f:
        json.dump(refs, f, indent=2)
    print(f"[collect_issues] Written {len(refs)} candidates → issue_candidates.json")

    # Phase 3 - build findings (closed issues with live workarounds)
    findings = build_findings(refs)

    with open("issue_findings.json", "w") as f:
        json.dump(findings, f, indent=2)
    print(f"[collect_issues] Emitted {len(findings)} findings → issue_findings.json")

    if findings:
        print("\n  id        severity   stale_days  title")
        print("  --------  ---------  ----------  -----")
        for fin in sorted(findings, key=lambda x: x["evidence"]["days_since_closed"], reverse=True):
            stale = fin["evidence"]["days_since_closed"]
            print(f"  {fin['id']:<8}  {fin['severity']:<9}  {stale:>10}  {fin['title'][:70]}")
    else:
        print("[collect_issues] No stale workarounds found.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collect GitHub issue workarounds.")
    parser.add_argument(
        "--root",
        default=".",
        help="Root directory to scan (default: current working directory)",
    )
    args = parser.parse_args()
    main(root=args.root)
