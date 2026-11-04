#!/usr/bin/env python3
"""Draw this folder's three figures from its quarterly and annual breach counts.

Run: python3 problems/cyber-hhs-breaches/figure.py

discovery-cyber-hhs-breaches.png counts breaches of 500 or more people per
quarter, split into Hacking/IT Incident and every other breach type.
people-cyber-hhs-breaches.png draws the people affected per year with the same
split, and names the single breach behind each year a lone record dominates.
cumulative-cyber-hhs-breaches.png redraws the quarterly counts as a running
total for the collection-wide cumulative index.

The split is drawn in the severity ramp: it is a harm category, and the AI and
human colours elsewhere in the collection mark who found something, which no
breach report records.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from lib.chart import SEVERITY_RAMP  # noqa: E402
from lib.cumulative import counts_chart  # noqa: E402
from lib.families import periodic_stacked  # noqa: E402
from lib.table import read_csv  # noqa: E402

SOURCE_URL = "https://ocrportal.hhs.gov/ocr/breach/breach_report.jsf"
SOURCE_LABEL = ("HHS OCR breach portal, current and archive listings, "
                "by breach submission date")
# A breach this large is named in the note: only a few clear the bar, and they
# are the bars a reader would otherwise mistake for a trend.
NAMED_AT = 50_000_000


def main_chart() -> None:
    rows = read_csv(HERE / "hhs-breaches-by-quarter.csv")
    last = rows[-1]
    periodic_stacked(
        HERE / "discovery-cyber-hhs-breaches.png",
        title="Health-data breaches reported to HHS",
        subtitle="Quarterly breaches affecting 500 or more people, "
                 "by type of breach",
        ylabel="Breaches submitted that quarter",
        periods=[row["quarter"] for row in rows],
        stacks=[
            ("Hacking/IT Incident", SEVERITY_RAMP[2],
             [int(row["hacking"]) for row in rows]),
            ("every other type", SEVERITY_RAMP[0],
             [int(row["other"]) for row in rows]),
        ],
        source_label=SOURCE_LABEL,
        source_url=SOURCE_URL,
        built_by=__file__,
        partial_last=(
            f"partial quarter\nthrough {last['data_through']}"
            if last["partial_quarter"] == "yes" else ""
        ),
    )


def dominant_breaches() -> str:
    """Name every single breach of NAMED_AT people or more, oldest first."""
    named = [
        f"{row['submitted'][:4]} {row['entity'].split(',')[0].rstrip('.')} "
        f"({int(row['individuals_affected']) / 1e6:.1f}M)"
        for row in read_csv(HERE / "hhs-breaches.csv")
        if int(row["individuals_affected"]) >= NAMED_AT
    ]
    return ("Single breaches of 50M+ people:\n" + " · ".join(named)
            if named else "")


def people_chart() -> None:
    rows = read_csv(HERE / "hhs-breaches-by-year.csv")
    last = rows[-1]
    periodic_stacked(
        HERE / "people-cyber-hhs-breaches.png",
        title="People affected by health-data breaches reported to HHS",
        subtitle="Annual total across breaches of 500 or more people, "
                 "by type of breach",
        ylabel="People affected (millions)",
        periods=[row["year"] for row in rows],
        stacks=[
            ("Hacking/IT Incident", SEVERITY_RAMP[2],
             [int(row["hacking_individuals"]) / 1e6 for row in rows]),
            ("every other type", SEVERITY_RAMP[0],
             [int(row["other_individuals"]) / 1e6 for row in rows]),
        ],
        source_label=SOURCE_LABEL,
        source_url=SOURCE_URL,
        built_by=__file__,
        partial_last=(
            f"partial year\nthrough {last['data_through']}"
            if last["partial_year"] == "yes" else ""
        ),
        note=dominant_breaches(),
    )


def cumulative() -> None:
    rows = read_csv(HERE / "hhs-breaches-by-quarter.csv")
    counts_chart(
        HERE / "cumulative-cyber-hhs-breaches.png",
        title="Health-data breaches reported to HHS: cumulative",
        ylabel="Breaches of 500+ people to date",
        period_labels=[row["quarter"] for row in rows],
        counts=[int(row["breaches"]) for row in rows],
        source_label=SOURCE_LABEL,
        source_url=SOURCE_URL,
        built_by=__file__,
    )


def main() -> None:
    main_chart()
    people_chart()
    cumulative()


if __name__ == "__main__":
    main()
