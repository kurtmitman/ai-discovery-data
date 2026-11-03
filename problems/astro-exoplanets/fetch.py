#!/usr/bin/env python3
"""Rebuild this folder's three generated CSVs from the NASA Exoplanet Archive.

Run: python3 problems/astro-exoplanets/fetch.py

The archive's Planetary Systems Composite Parameters table (`pscomppars`) has
one row per confirmed planet, with the month its discovery was published
(`disc_pubdate`, YYYY-MM), the facility that made the discovery, and the
discovery reference. One TAP query reads the whole table.

Every planet gets two flags:

- `archival_kepler`: the discovery facility is Kepler or K2 and the discovery
  was published from November 2018 on. The spacecraft was retired on
  2018-10-30, so these planets were found in data already in the archive:
  better inference on old observations, not a new telescope.
- `ai_paper`: the discovery reference is one of the papers listed in the
  hand-maintained exoplanets-ai-papers.csv, each of which states a machine-
  learning method in its own title.

Three CSVs come out: the per-planet ledger and its quarterly and annual
rollups, with every confirmation in exactly one band: an AI paper, archival
Kepler/K2 by any other method, or everything else.

Planets published after lib/dates.py's AS_OF_DATE are dropped, so a refetch
reproduces the committed window.
"""

from __future__ import annotations

import csv
import html
import io
import re
import sys
import urllib.parse
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from lib.dates import AS_OF_DATE  # noqa: E402
from lib.table import read_csv, write_csv  # noqa: E402
from lib.web import fetch  # noqa: E402

TAP = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"
COLUMNS = ("pl_name", "disc_pubdate", "disc_year", "disc_method",
           "disc_facility", "disc_refname")
QUERY = f"select {','.join(COLUMNS)} from pscomppars"
KEPLER = {"Kepler", "K2"}
RETIRED = "2018-11"   # first month after Kepler's 2018-10-30 retirement
BANDS = ("ai_paper", "archival_other", "other")


def reference(cell: str) -> tuple[str, str]:
    """Plain citation text and ADS bibcode from the archive's HTML link."""
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", cell))).strip()
    found = re.search(r"/abs/([^/\s\"']+)", cell)
    return text, urllib.parse.unquote(found.group(1)) if found else ""


def band(row: dict) -> str:
    if row["ai_paper"] == "yes":
        return "ai_paper"
    return "archival_other" if row["archival_kepler"] == "yes" else "other"


def rollup(rows: list[dict], key, labels: list[str], period: str,
           through: str) -> list[dict]:
    counts: dict[str, dict] = defaultdict(lambda: defaultdict(int))
    for row in rows:
        counts[key(row["disc_pubdate"])][band(row)] += 1
    last = labels[-1]
    return [
        {
            period: label,
            "confirmed": sum(counts[label].values()),
            **{name: counts[label][name] for name in BANDS},
            f"partial_{period}": "yes" if label == last else "no",
            "data_through": through if label == last else "",
        }
        for label in labels
    ]


def quarter_of(month: str) -> str:
    return f"{month[:4]}-Q{(int(month[5:7]) - 1) // 3 + 1}"


def main() -> None:
    url = f"{TAP}?{urllib.parse.urlencode({'query': QUERY, 'format': 'csv'})}"
    table = list(csv.DictReader(io.StringIO(fetch(url).decode("utf-8"))))
    missing = set(COLUMNS) - set(table[0]) if table else set(COLUMNS)
    if missing:
        raise SystemExit(f"archive query returned no {sorted(missing)} columns")
    ai_papers = {row["bibcode"] for row in read_csv(HERE / "exoplanets-ai-papers.csv")}
    cutoff = AS_OF_DATE.isoformat()[:7]
    rows, undated = [], 0
    for raw in table:
        month = raw["disc_pubdate"].strip()
        if not re.fullmatch(r"\d{4}-\d{2}", month):
            undated += 1
            continue
        if month > cutoff:
            continue
        text, bibcode = reference(raw["disc_refname"])
        rows.append({
            "pl_name": raw["pl_name"],
            "disc_pubdate": month,
            "disc_year": raw["disc_year"],
            "disc_method": raw["disc_method"],
            "disc_facility": raw["disc_facility"],
            "reference": text,
            "bibcode": bibcode,
            "archival_kepler": "yes" if (raw["disc_facility"] in KEPLER
                                         and month >= RETIRED) else "no",
            "ai_paper": "yes" if bibcode in ai_papers else "no",
        })
    if undated:
        raise SystemExit(f"{undated} planets carry no YYYY-MM disc_pubdate")
    unmatched = ai_papers - {row["bibcode"] for row in rows}
    if unmatched:
        raise SystemExit(f"register papers with no planet in the archive: {unmatched}")
    rows.sort(key=lambda r: (r["disc_pubdate"], r["pl_name"]))
    through = AS_OF_DATE.isoformat()
    first, last = rows[0]["disc_pubdate"], cutoff
    years = [str(y) for y in range(int(first[:4]), int(last[:4]) + 1)]
    quarters = [f"{y}-Q{q}" for y in years for q in range(1, 5)
                if quarter_of(first) <= f"{y}-Q{q}" <= quarter_of(last)]
    write_csv(HERE / "exoplanets-confirmed.csv", rows)
    write_csv(HERE / "exoplanets-by-year.csv",
              rollup(rows, lambda m: m[:4], years, "year", through))
    write_csv(HERE / "exoplanets-by-quarter.csv",
              rollup(rows, quarter_of, quarters, "quarter", through))
    print(f"exoplanets: {len(rows)} confirmed planets published {first}–{last}; "
          f"{sum(r['archival_kepler'] == 'yes' for r in rows)} archival Kepler/K2, "
          f"{sum(r['ai_paper'] == 'yes' for r in rows)} from AI-method papers")


if __name__ == "__main__":
    main()
