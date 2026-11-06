#!/usr/bin/env python3
"""The depletion model's closed-stock case: Kepler's candidate list.

Run: python3 analysis/depletion/kepler_koi.py   (needs numpy and matplotlib)

Kepler's candidate list (the KOI cumulative table) has been frozen since the
final DR25 catalogue of 2017, and the telescope stopped collecting data in
October 2018. From then on the list is a closed stock: no new candidates
arrive, and each one is either still open, confirmed as a planet, or ruled a
false positive. With no inflow the model's hazard is directly observable as
confirmations per year over candidates still open, with no need to infer the
stock from ages as the curl case does.

The KOI table records only today's disposition, not when it changed, so the
open stock at the start of a year is rebuilt as the candidates still open now
plus those confirmed in that year or later. A confirmation is dated by the
discovery publication month of the matching planet in
problems/astro-exoplanets/exoplanets-confirmed.csv (matched on `kepler_name`),
which also carries the machine-learning paper flag. False positives are left
out of the stock: their decision dates are not recorded.

Writes kepler-koi-by-year.csv and depletion-kepler-hazard.png beside this file
and prints the numbers the README quotes.
"""

from __future__ import annotations

import csv
import io
import sys
import urllib.parse
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from lib.palette import AI, HUMAN, NEUTRAL  # noqa: E402
from lib.table import read_csv, write_csv  # noqa: E402
from lib.web import fetch  # noqa: E402

TAP = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"
QUERY = "select kepoi_name,kepler_name,koi_disposition from cumulative"
LEDGER = ROOT / "problems" / "astro-exoplanets" / "exoplanets-confirmed.csv"
FIRST_YEAR = 2010
CLOSED_FROM = 2017      # DR25, the final candidate catalogue
BASELINE = range(2017, 2021)
ML_YEARS = range(2021, 2024)
AFTER = range(2024, 2026)


def koi_table() -> list[dict]:
    url = f"{TAP}?{urllib.parse.urlencode({'query': QUERY, 'format': 'csv'})}"
    return list(csv.DictReader(io.StringIO(fetch(url).decode("utf-8"))))


def build() -> tuple[list[dict], dict]:
    kois = koi_table()
    planets = {row["pl_name"]: row for row in read_csv(LEDGER)}
    dispositions = Counter(row["koi_disposition"] for row in kois)
    confirmed = [row for row in kois if row["koi_disposition"] == "CONFIRMED"]
    matched = [planets[row["kepler_name"]] for row in confirmed
               if row["kepler_name"] in planets]
    open_now = dispositions["CANDIDATE"]
    by_year: dict[int, Counter] = defaultdict(Counter)
    for planet in matched:
        year = int(planet["disc_pubdate"][:4])
        bucket = by_year[year]
        bucket["confirmed"] += 1
        bucket["ai_paper" if planet["ai_paper"] == "yes" else "other"] += 1
        bucket[planet["reference"]] += 1
    # Run to the ledger's latest year, so a year with no confirmation shows.
    last = max(int(row["disc_pubdate"][:4]) for row in planets.values())
    rows, later = [], 0
    for year in range(last, FIRST_YEAR - 1, -1):
        bucket = by_year.get(year, Counter())
        stock = open_now + later + bucket["confirmed"]
        papers = Counter({k: v for k, v in bucket.items()
                          if k not in ("confirmed", "ai_paper", "other")})
        top = papers.most_common(1)[0] if papers else ("", 0)
        rows.append({
            "year": year,
            "confirmed": bucket["confirmed"],
            "ai_paper": bucket["ai_paper"],
            "other": bucket["other"],
            "open_at_start": stock,
            "hazard": f"{bucket['confirmed'] / stock:.4f}",
            "largest_paper": top[0],
            "largest_paper_count": top[1],
        })
        later += bucket["confirmed"]
    rows.reverse()
    info = {"kois": len(kois), "dispositions": dispositions,
            "confirmed": len(confirmed), "matched": len(matched),
            "open_now": open_now, "read": date.today().isoformat()}
    return rows, info


def pooled(rows: list[dict], years: range) -> tuple[int, float]:
    picked = [row for row in rows if int(row["year"]) in years]
    found = sum(int(row["confirmed"]) for row in picked)
    exposure = sum(int(row["open_at_start"]) for row in picked)
    return found, found / exposure


def figure(rows: list[dict]) -> None:
    years = [int(row["year"]) for row in rows]
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8))
    other = [int(row["other"]) for row in rows]
    axes[0].bar(years, other, color=HUMAN, label="other methods")
    axes[0].bar(years, [int(row["ai_paper"]) for row in rows], bottom=other,
                color=AI, label="paper states a machine-learning method")
    axes[0].set_yscale("symlog", linthresh=10)
    axes[0].set_title("Kepler candidates confirmed per year (symlog)",
                      fontsize=10, loc="left")
    axes[0].legend(frameon=False, fontsize=8, loc="upper right")
    # A year with no confirmation has no point on a log axis; it is named
    # instead of being drawn at an invented floor.
    drawn = [row for row in rows if int(row["confirmed"])]
    axes[1].plot([int(row["year"]) for row in drawn],
                 [float(row["hazard"]) for row in drawn], "o-", color=HUMAN,
                 markersize=4)
    for row in rows:
        if not int(row["confirmed"]):
            axes[1].annotate(f"{row['year']}: none", (int(row["year"]), 1.5e-3),
                             fontsize=8, color="#555555", ha="center")
    for row in rows:
        if int(row["ai_paper"]):
            axes[1].plot(int(row["year"]), float(row["hazard"]), "o",
                         color=AI, markersize=7)
    axes[1].axvspan(CLOSED_FROM - 0.5, years[-1] + 0.5, color=NEUTRAL, alpha=0.15)
    axes[1].text(CLOSED_FROM - 0.3, 0.5, "closed stock\n(DR25 on)", fontsize=8,
                 color="#555555", va="top")
    axes[1].set_yscale("log")
    axes[1].set_title("Confirmations / candidates still open (log)",
                      fontsize=10, loc="left")
    for ax in axes:
        ax.xaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", color="#e6e6e6", linewidth=0.8)
        ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(HERE / "depletion-kepler-hazard.png", dpi=150)
    plt.close(fig)


def main() -> None:
    rows, info = build()
    write_csv(HERE / "kepler-koi-by-year.csv", rows)
    d = info["dispositions"]
    print(f"KOI table read {info['read']}: {info['kois']:,} candidates; "
          f"{d['CONFIRMED']:,} confirmed, {d['FALSE POSITIVE']:,} false positive, "
          f"{d['CANDIDATE']:,} still open; {info['matched']:,} of the confirmed "
          f"matched to the planet ledger")
    for row in rows:
        print(f"  {row['year']}: {int(row['confirmed']):5d} confirmed "
              f"({int(row['ai_paper']):3d} ML paper), open at start "
              f"{int(row['open_at_start']):5d}, hazard {row['hazard']}, "
              f"largest: {row['largest_paper']} ({row['largest_paper_count']})")
    for label, years in (("baseline", BASELINE), ("ML years", ML_YEARS),
                         ("after", AFTER)):
        found, rate = pooled(rows, years)
        print(f"{label} {years.start}–{years.stop - 1}: {found} confirmed, "
              f"pooled hazard {rate:.4f}/yr")
    ml = sum(int(r["ai_paper"]) for r in rows if int(r["year"]) in ML_YEARS)
    start = next(int(r["open_at_start"]) for r in rows if int(r["year"]) == ML_YEARS.start)
    print(f"ML papers took {ml} of the {start:,} open at the start of "
          f"{ML_YEARS.start} ({ml / start:.1%})")
    for year in (2014, 2016):
        row = next(r for r in rows if int(r["year"]) == year)
        print(f"{year}: {row['confirmed']} confirmed, "
              f"{int(row['confirmed']) / int(row['open_at_start']):.0%} of the open stock; "
              f"largest {row['largest_paper']} ({row['largest_paper_count']})")
    figure(rows)
    print("wrote kepler-koi-by-year.csv and depletion-kepler-hazard.png")


if __name__ == "__main__":
    main()
