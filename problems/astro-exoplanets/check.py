#!/usr/bin/env python3
"""Recompute this page's fact lines from the CSVs beside it."""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from lib.prose import annualized, by_year_line, missing, prose, report  # noqa: E402
from lib.table import read_csv  # noqa: E402


def main() -> int:
    ledger = read_csv(HERE / "exoplanets-confirmed.csv")
    annual = read_csv(HERE / "exoplanets-by-year.csv")
    papers = read_csv(HERE / "exoplanets-ai-papers.csv")
    year = {row["year"]: row for row in annual}
    current = next(row for row in annual if row["partial_year"] == "yes")
    through, part = current["data_through"], current["year"]
    confirmed = {y: int(row["confirmed"]) for y, row in year.items()}
    pace = annualized(confirmed[part], through)
    mean = sum(confirmed[str(y)] for y in range(2023, 2026)) / 3
    recent = [row for row in annual if 2016 <= int(row["year"]) <= 2025]

    by_paper = Counter(row["reference"] for row in ledger if row["ai_paper"] == "yes")
    top_paper, top_count = by_paper.most_common(1)[0]
    part_ai = Counter(row["reference"] for row in ledger
                      if row["ai_paper"] == "yes" and row["disc_pubdate"][:4] == part)
    part_paper, part_count = part_ai.most_common(1)[0] if part_ai else ("none", 0)
    archival = [row for row in ledger if row["archival_kepler"] == "yes"]
    archival_ai = sum(row["ai_paper"] == "yes" for row in archival)
    archival_years = Counter(row["disc_pubdate"][:4] for row in archival)
    archival_peak = max(archival_years, key=archival_years.get)
    ai_total = sum(by_paper.values())

    claims = {
        f"partial through {through}": "coverage field",
        f"{confirmed[part]} confirmations published through {through} "
        f"annualize to about {round(pace)} against {confirmed['2025']} in 2025 "
        f"and a {mean:.0f}/year mean over 2023–2025; one paper holds "
        f"{part_count} of the {confirmed[part]}": "verdict clause",
        f"**rows:** {len(ledger):,} confirmed planets published "
        f"{ledger[0]['disc_pubdate']} to {ledger[-1]['disc_pubdate']}":
            "rows fact",
        f"**by-year (2016–2025):** {by_year_line(recent, 'confirmed')}":
            "by-year fact",
        f"**{part} (through {through}):** {confirmed[part]} planets; "
        f"annualizes to about {round(pace)}": "part-year fact",
        f"**{part} concentration:** {part_paper} accounts for {part_count} of "
        f"the {confirmed[part]}": "concentration fact",
        f"**archival Kepler/K2:** {len(archival):,} planets published from "
        f"November 2018 on, {archival_ai} of them ({archival_ai / len(archival):.0%})"
        f" from register papers; the peak year is {archival_peak} with "
        f"{archival_years[archival_peak]}": "archival fact",
        f"**machine-learning register:** {ai_total:,} planets across "
        f"{len(papers)} papers, {ai_total / len(ledger):.1%} of all confirmed "
        f"planets; the largest is {top_paper} with {top_count}":
            "register fact",
    }
    failures = missing(prose(HERE), claims)
    for paper in papers:
        if paper["quote"] not in prose(HERE):
            failures.append(f"register quote for {paper['reference']} is not "
                            "quoted verbatim in the README")
    return report(failures)


if __name__ == "__main__":
    raise SystemExit(main())
