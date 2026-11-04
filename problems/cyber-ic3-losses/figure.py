#!/usr/bin/env python3
"""Draw this folder's three figures from the transcribed IC3 annual table.

Run: python3 problems/cyber-ic3-losses/figure.py

discovery-cyber-ic3-losses.png counts ransomware complaints per year, the row
of the IC3 crime-type tables closest to the exploitation series this
collection tracks. losses-cyber-ic3-losses.png draws total reported losses per
year in billions of dollars, all crime types together, with the ransomware
losses stated in the note rather than stacked: at under 1% of the total they
would not show. cumulative-cyber-ic3-losses.png redraws the ransomware
complaints as a running total for the collection-wide cumulative index.

Every bar is a value one annual report states for its own year; nothing is
reconciled across reports.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from lib.chart import SEVERITY_RAMP, VENDOR  # noqa: E402
from lib.cumulative import counts_chart  # noqa: E402
from lib.families import periodic_stacked  # noqa: E402
from lib.table import read_csv  # noqa: E402

SOURCE_URL = "https://www.ic3.gov/AnnualReport/Reports"
SOURCE_LABEL = "FBI Internet Crime Reports 2015–2025, each year's own report"


def main_chart() -> None:
    rows = read_csv(HERE / "ic3-by-year.csv")
    periodic_stacked(
        HERE / "discovery-cyber-ic3-losses.png",
        title="Ransomware complaints to the FBI's IC3",
        subtitle="Complaints identified as ransomware per year, as each "
                 "annual Internet Crime Report states",
        ylabel="Ransomware complaints that year",
        periods=[row["year"] for row in rows],
        stacks=[("", SEVERITY_RAMP[2],
                 [int(row["ransomware_complaints"]) for row in rows])],
        source_label=SOURCE_LABEL,
        source_url=SOURCE_URL,
        built_by=__file__,
        note="No 2026 report yet; IC3 publishes each year's in the spring "
             "after.",
    )


def losses_chart() -> None:
    rows = read_csv(HERE / "ic3-by-year.csv")
    ransomware = sum(int(row["ransomware_losses_usd"]) for row in rows)
    total = sum(int(row["losses_usd"]) for row in rows)
    periodic_stacked(
        HERE / "losses-cyber-ic3-losses.png",
        title="Losses reported to the FBI's IC3",
        subtitle="Reported losses per year across all crime types, as each "
                 "annual report states them",
        ylabel="Reported losses (billions of dollars)",
        periods=[row["year"] for row in rows],
        # Vendor grey: the totals are the agency's own published figures, not
        # recounted here, and most are rounded to the nearest $0.1 billion.
        stacks=[("", VENDOR, [int(row["losses_usd"]) / 1e9 for row in rows])],
        source_label=SOURCE_LABEL,
        source_url=SOURCE_URL,
        built_by=__file__,
        note=f"Ransomware is {100 * ransomware / total:.1f}% of the reported "
             "losses over these years.",
    )


def cumulative() -> None:
    rows = read_csv(HERE / "ic3-by-year.csv")
    counts_chart(
        HERE / "cumulative-cyber-ic3-losses.png",
        title="Ransomware complaints to the FBI's IC3: cumulative",
        ylabel="Ransomware complaints to date",
        period_labels=[row["year"] for row in rows],
        counts=[int(row["ransomware_complaints"]) for row in rows],
        source_label=SOURCE_LABEL,
        source_url=SOURCE_URL,
        built_by=__file__,
    )


def main() -> None:
    main_chart()
    losses_chart()
    cumulative()


if __name__ == "__main__":
    main()
