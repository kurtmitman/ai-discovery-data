#!/usr/bin/env python3
"""Date the commit that introduced each curl CVE, and count curl's commits per year.

Run: python3 analysis/depletion/curl_ages.py /path/to/curl/clone

curl's own advisory record (https://curl.se/docs/vuln.json, the source of
problems/cyber-curl) is read whole. Most records carry a GIT range whose
`introduced` event names the commit that brought the flaw in; the rest, mostly
2011–2016 advisories, name only the first affected release, and are dated by
the commit that release's tag points at. A release older than curl's first
commit (1999-12-29, "Initial revision") is dated to that commit, the lump the
model treats separately. A clone of https://github.com/curl/curl supplies the
dates. Only commit objects are read, so a treeless clone is enough:

    git clone --filter=tree:0 --no-checkout https://github.com/curl/curl

Two CSVs come out:

- curl-bug-ages.csv: one row per CVE with its disclosure date, the introducing
  commit and its committer date, how that commit was found (`commit`,
  `release_tag` or `before_history`), the age in years between the two,
  severity, and the AI marker by the same classifier problems/cyber-curl uses.
- curl-commits-by-year.csv: commits reachable from the clone's HEAD per
  calendar year, the inflow proxy the model in model.py uses.

An earlier version read OSV's mirror of the record, which holds only the
records with a GIT range and so dropped 27 disclosures, 26 of them before 2020;
the full record keeps the pre-AI disclosure counts the model calibrates on
whole. The counts here match problems/cyber-curl's vendored series.
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

URL = "https://curl.se/docs/vuln.json"
IMPORT_COMMIT = "ae1912cb0d494b48d514d937826c9fe83ec96c4d"  # "Initial revision"


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
    return [entry for entry in json.loads(fetch(URL))
            if (entry.get("published") or "")[:4].isdigit()]


def first_introduced(record: dict, kind: str) -> str | None:
    (affected,) = record["affected"]
    for found in (r for r in affected["ranges"] if r["type"] == kind):
        events = [e["introduced"] for e in found["events"] if "introduced" in e]
        if events:
            return events[0]
    return None


def introduced_commit(repo: Path, record: dict) -> tuple[str, str]:
    """The introducing commit and how it was found."""
    commit = first_introduced(record, "GIT")
    if commit:
        return commit, "commit"
    version = first_introduced(record, "SEMVER")
    if version is None:
        raise SystemExit(f"{record['id']}: no GIT or SEMVER introduced event")
    tag = "curl-" + version.replace(".", "_")
    found = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", "--quiet",
         f"refs/tags/{tag}^{{commit}}"],
        capture_output=True, text=True,
    )
    if found.returncode == 0:
        return found.stdout.strip(), "release_tag"
    # No tag: a release older than the repository's first commit.
    return IMPORT_COMMIT, "before_history"


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
    intro = {r["id"]: introduced_commit(repo, r) for r in recs}
    times = commit_times(repo, sorted({sha for sha, _ in intro.values()}))
    rows = []
    for record in recs:
        published = datetime.fromisoformat(record["published"].replace("Z", "+00:00"))
        sha, basis = intro[record["id"]]
        born = times[sha]
        names = finders(record)
        year = published.year
        is_ai = any(classify(name, year) == "ai" for name in names)
        bands = {band(name, year) for name in names}
        rows.append({
            "cve": record["aliases"][0] if record.get("aliases") else record["id"],
            "published": published.date().isoformat(),
            "introduced_commit": sha,
            "introduced": born.date().isoformat(),
            "introduced_basis": basis,
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
    bases = Counter(basis for _, basis in intro.values())
    print(f"curl ages: {len(rows)} CVEs through {latest}; 2026: {by_year['2026']}; "
          f"dated by {dict(bases)}")
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
