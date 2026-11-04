#!/usr/bin/env python3
"""Draw this folder's three figures from its quarterly and annual rollups.

Run: python3 problems/astro-exoplanets/figure.py

discovery-astro-exoplanets.png counts confirmed planets per quarter by the
month their discovery was published, in three bands: planets from a paper in
the machine-learning register, Kepler/K2 planets published after the
spacecraft's retirement by any other method, and everything else.
archival-astro-exoplanets.png draws only the post-retirement Kepler/K2 planets
per year, the subset found in data that was already in the archive, split the
same way. cumulative-astro-exoplanets.png redraws the quarterly confirmations
as a running total for the collection-wide cumulative index.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from lib.chart import AI, HUMAN, HUMAN_SOFT  # noqa: E402
from lib.cumulative import counts_chart  # noqa: E402
from lib.families import periodic_stacked  # noqa: E402
from lib.table import read_csv  # noqa: E402

SOURCE_URL = "https://exoplanetarchive.ipac.caltech.edu/"
SOURCE_LABEL = ("NASA Exoplanet Archive, Planetary Systems Composite "
                "Parameters, by discovery publication month")


def main_chart() -> None:
    rows = read_csv(HERE / "exoplanets-by-quarter.csv")
    last = rows[-1]
    periodic_stacked(
        HERE / "discovery-astro-exoplanets.png",
        title="Confirmed exoplanets",
        subtitle="Planets per quarter by the month their discovery was "
                 "published",
        ylabel="Planets confirmed that quarter",
        periods=[row["quarter"] for row in rows],
        stacks=[
            ("everything else", HUMAN, [int(row["other"]) for row in rows]),
            ("archival Kepler/K2, other methods", HUMAN_SOFT,
             [int(row["archival_other"]) for row in rows]),
            ("paper states a machine-learning method", AI,
             [int(row["ai_paper"]) for row in rows]),
        ],
        source_label=SOURCE_LABEL,
        source_url=SOURCE_URL,
        built_by=__file__,
        partial_last=(
            f"partial quarter\nthrough {last['data_through']}"
            if last["partial_quarter"] == "yes" else ""
        ),
    )


def archival_chart() -> None:
    rows = [row for row in read_csv(HERE / "exoplanets-by-year.csv")
            if int(row["year"]) >= 2018]
    ledger = read_csv(HERE / "exoplanets-confirmed.csv")
    archival_ai = {}
    for row in ledger:
        if row["archival_kepler"] == "yes" and row["ai_paper"] == "yes":
            year = row["disc_pubdate"][:4]
            archival_ai[year] = archival_ai.get(year, 0) + 1
    last = rows[-1]
    periodic_stacked(
        HERE / "archival-astro-exoplanets.png",
        title="Exoplanets found in archived Kepler and K2 data",
        subtitle="Kepler/K2 planets published after the spacecraft's "
                 "October 2018 retirement",
        ylabel="Planets published that year",
        periods=[row["year"] for row in rows],
        stacks=[
            ("other methods", HUMAN_SOFT,
             [int(row["archival_other"]) for row in rows]),
            ("paper states a machine-learning method", AI,
             [archival_ai.get(row["year"], 0) for row in rows]),
        ],
        source_label=SOURCE_LABEL,
        source_url=SOURCE_URL,
        built_by=__file__,
        partial_last=(
            f"partial year\nthrough {last['data_through']}"
            if last["partial_year"] == "yes" else ""
        ),
        note="2018 holds only November and December.",
    )


def cumulative() -> None:
    rows = read_csv(HERE / "exoplanets-by-quarter.csv")
    counts_chart(
        HERE / "cumulative-astro-exoplanets.png",
        title="Confirmed exoplanets: cumulative",
        ylabel="Planets confirmed to date",
        period_labels=[row["quarter"] for row in rows],
        counts=[int(row["confirmed"]) for row in rows],
        source_label=SOURCE_LABEL,
        source_url=SOURCE_URL,
        built_by=__file__,
    )


def main() -> None:
    main_chart()
    archival_chart()
    cumulative()


if __name__ == "__main__":
    main()
