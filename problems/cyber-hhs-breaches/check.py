#!/usr/bin/env python3
"""Recompute this page's fact lines from the CSVs beside it."""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from lib.prose import annualized, by_year_line, missing, prose, report  # noqa: E402
from lib.table import read_csv  # noqa: E402


def main() -> int:
    ledger = read_csv(HERE / "hhs-breaches.csv")
    annual = read_csv(HERE / "hhs-breaches-by-year.csv")
    year = {row["year"]: row for row in annual}
    current = next(row for row in annual if row["partial_year"] == "yes")
    through = current["data_through"]
    part = current["year"]
    hacking = {y: int(row["hacking"]) for y, row in year.items()}
    pace = annualized(hacking[part], through)
    mean = sum(hacking[str(y)] for y in range(2023, 2026)) / 3
    listings = {name: sum(1 for row in ledger if row["listing"] == name)
                for name in ("current", "archive")}
    share = {y: hacking[y] / int(year[y]["breaches"]) for y in ("2010", "2025")}
    people = {y: int(row["individuals_affected"]) for y, row in year.items()}
    top_years = sorted((y for y in people if y != part), key=people.get,
                       reverse=True)[:2]
    largest = max(ledger, key=lambda row: int(row["individuals_affected"]))
    largest_n = int(largest["individuals_affected"])
    largest_year = largest["submitted"][:4]
    hacking_people = sum(int(row["hacking_individuals"]) for row in annual)
    all_people = sum(people.values())

    claims = {
        f"partial through {through}": "coverage field",
        f"{hacking[part]} Hacking/IT Incident breaches through {through} "
        f"annualize to about {round(pace)} against {hacking['2025']} in 2025 "
        f"and a {mean:.0f}/year mean over 2023–2025": "verdict clause",
        f"**rows:** {len(ledger):,} breaches submitted "
        f"{ledger[0]['submitted']} to {through}; {listings['current']:,} from "
        f"the current listing and {listings['archive']:,} from the archive":
            "rows fact",
        f"**hacking by year:** "
        f"{by_year_line(annual, 'hacking', skip_zero=True)}": "hacking by-year",
        f"**all types by year:** "
        f"{by_year_line(annual, 'breaches', skip_zero=True)}": "all by-year",
        f"**hacking share:** {share['2010']:.0%} of 2010's breaches and "
        f"{share['2025']:.0%} of 2025's": "hacking share fact",
        f"**{part} (through {through}):** {int(current['breaches'])} breaches, "
        f"{hacking[part]} of them Hacking/IT Incident; the hacking count "
        f"annualizes to about {round(pace)}": "part-year fact",
        f"**people affected:** {all_people / 1e6:,.0f} million across all "
        f"rows, {hacking_people / all_people:.0%} of them in Hacking/IT "
        "Incident breaches": "people total fact",
        f"**largest years:** {top_years[0]}: {people[top_years[0]] / 1e6:.1f} "
        f"million people; {top_years[1]}: {people[top_years[1]] / 1e6:.1f} "
        "million": "largest years fact",
        f"**largest breach:** {largest['entity']}, {largest_n:,} people, "
        f"submitted {largest['submitted']}, {largest_n / people[largest_year]:.0%}"
        f" of {largest_year}'s total": "largest breach fact",
    }
    failures = missing(prose(HERE), claims)
    # The rollups are derived from the ledger; a stale rollup beside a
    # refreshed ledger would make every line above quietly disagree.
    if sum(int(row["breaches"]) for row in annual) != len(ledger):
        failures.append("hhs-breaches-by-year.csv does not sum to the ledger")
    return report(failures)


if __name__ == "__main__":
    raise SystemExit(main())
