#!/usr/bin/env python3
"""Date the commit that introduced each curl CVE, and count curl's commits per year.

Run: python3 analysis/depletion/curl_ages.py /path/to/curl/clone

curl's own advisory record (https://curl.se/docs/vuln.json, the source of
problems/cyber-curl) is mirrored record by record into OSV's public bucket as
GIT/CURL-CVE-*.json, and every record carries a GIT range whose `introduced`
event names the commit that brought the flaw in. A clone of
https://github.com/curl/curl dates that commit. Only commit objects are read,
so a treeless clone is enough:

    git clone --filter=tree:0 --no-checkout https://github.com/curl/curl

Two CSVs come out:

- curl-bug-ages.csv: one row per CVE with its disclosure date, the introducing
  commit and its committer date, the age in years between the two, severity,
  and the AI marker by the same classifier problems/cyber-curl uses.
- curl-commits-by-year.csv: commits reachable from the clone's HEAD per
  calendar year, the inflow proxy the model in model.py uses.

The bucket is read rather than curl.se because the record is identical and
storage.googleapis.com is reachable from more sandboxes; the 2026-09-02 counts
here (45 disclosures, 22 AI-marked) match problems/cyber-curl's vendored series.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from lib.credits import band, classify  # noqa: E402
from lib.table import write_csv  # noqa: E402
from lib.web import fetch  # noqa: E402

BUCKET = "https://osv-vulnerabilities.storage.googleapis.com"
LISTING = (
    "https://storage.googleapis.com/storage/v1/b/osv-vulnerabilities/o"
    "?prefix=GIT/CURL-&maxResults=1000&fields=items(name),nextPageToken"
)


def _curl_finders():
    """problems/cyber-curl/fetch.py's finders(), so credits split identically."""
    spec = importlib.util.spec_from_file_location(
        "curl_fetch", ROOT / "problems" / "cyber-curl" / "fetch.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.finders


finders = _curl_finders()


def records() -> list[dict]:
    listing = json.loads(fetch(LISTING))
    if listing.get("nextPageToken"):
        raise SystemExit("OSV listing is paginated now; follow nextPageToken")
    names = sorted(item["name"] for item in listing["items"])
    return [json.loads(fetch(f"{BUCKET}/{name}")) for name in names]


def introduced_commit(record: dict) -> str:
    (affected,) = record["affected"]
    (git,) = [r for r in affected["ranges"] if r["type"] == "GIT"]
    first = [e["introduced"] for e in git["events"] if "introduced" in e]
    return first[0]


def commit_times(repo: Path, commits: list[str]) -> dict[str, datetime]:
    """Committer time of each commit, read from the raw objects.

    `git cat-file --batch` reads only the commit objects themselves; `git show`
    would make a treeless clone fetch trees on demand, one round trip each.
    """
    result = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "--batch"],
        input="\n".join(commits) + "\n",
        capture_output=True,
        text=True,
        check=True,
    )
    times: dict[str, datetime] = {}
    sha = None
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[1] == "commit" and len(parts[0]) == 40:
            sha = parts[0]
        elif line.startswith("committer ") and sha is not None:
            stamp = int(line.rsplit(" ", 2)[1])
            times[sha] = datetime.fromtimestamp(stamp, tz=timezone.utc)
            sha = None
    missing = set(commits) - set(times)
    if missing:
        raise SystemExit(f"{len(missing)} introducing commits not in the clone")
    return times


def decimal_year(moment: datetime) -> float:
    start = datetime(moment.year, 1, 1, tzinfo=timezone.utc)
    end = datetime(moment.year + 1, 1, 1, tzinfo=timezone.utc)
    return moment.year + (moment - start) / (end - start)


def build_ages(repo: Path) -> list[dict]:
    recs = records()
    intro = {r["id"]: introduced_commit(r) for r in recs}
    times = commit_times(repo, sorted(set(intro.values())))
    rows = []
    for record in recs:
        published = datetime.fromisoformat(record["published"].replace("Z", "+00:00"))
        born = times[intro[record["id"]]]
        names = finders(record)
        year = published.year
        is_ai = any(classify(name, year) == "ai" for name in names)
        bands = {band(name, year) for name in names}
        rows.append({
            "cve": record["aliases"][0] if record.get("aliases") else record["id"],
            "published": published.date().isoformat(),
            "introduced_commit": intro[record["id"]],
            "introduced": born.date().isoformat(),
            "age_years": f"{decimal_year(published) - decimal_year(born):.3f}",
            "severity": (record.get("database_specific") or {}).get("severity", ""),
            "ai_marker": "yes" if is_ai else "no",
            "finder_band": next(
                (b for b in ("explicit_ai", "ai_affiliated", "fuzz") if b in bands),
                "other",
            ),
            "finders": "; ".join(names),
        })
    rows.sort(key=lambda row: (row["published"], row["cve"]))
    latest = rows[-1]["published"]
    by_year = Counter(row["published"][:4] for row in rows)
    print(f"curl ages: {len(rows)} CVEs through {latest}; 2026: {by_year['2026']}")
    return rows


def build_commits(repo: Path) -> list[dict]:
    result = subprocess.run(
        ["git", "-C", str(repo), "log", "--format=%ct", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    stamps = [int(s) for s in result.stdout.split()]
    moments = [datetime.fromtimestamp(s, tz=timezone.utc) for s in stamps]
    latest = max(moments)
    per_year = Counter(m.year for m in moments)
    return [
        {
            "year": year,
            "commits": per_year[year],
            "partial_year": "yes" if year == latest.year else "no",
            "data_through": latest.date().isoformat() if year == latest.year else "",
        }
        for year in sorted(per_year)
    ]


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    repo = Path(sys.argv[1])
    write_csv(HERE / "curl-bug-ages.csv", build_ages(repo))
    write_csv(HERE / "curl-commits-by-year.csv", build_commits(repo))


if __name__ == "__main__":
    main()
