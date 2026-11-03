#!/usr/bin/env python3
"""Recompute this page's fact lines from the CSV beside it."""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from lib.prose import missing, prose, report  # noqa: E402
from lib.table import read_csv  # noqa: E402


def millions(dollars: int) -> str:
    return f"${dollars / 1e6:.1f} million"


def billions(dollars: int) -> str:
    return f"${dollars / 1e9:,.2f} billion"


def main() -> int:
    rows = read_csv(HERE / "ic3-by-year.csv")
    by = {row["year"]: row for row in rows}
    first, last = rows[0]["year"], rows[-1]["year"]
    prior = rows[:-1]
    complaints = {y: int(r["ransomware_complaints"]) for y, r in by.items()}
    losses = {y: int(r["ransomware_losses_usd"]) for y, r in by.items()}
    totals = {y: int(r["losses_usd"]) for y, r in by.items()}
    mean = sum(complaints[r["year"]] for r in prior) / len(prior)
    peak = max(losses, key=losses.get)
    share = sum(losses.values()) / sum(totals.values())
    line = " · ".join(f"{y}: {complaints[y]:,}" for y in by)
    biggest = max(by, key=lambda y: int(by[y]["complaints"]))

    claims = {
        f"Coverage:** {first}–{last}, one row per annual report": "coverage",
        f"{complaints[last]:,} ransomware complaints in {last} against "
        f"{complaints[str(int(last) - 1)]:,} in {int(last) - 1} and a "
        f"{mean:,.0f}/year mean over {first}–{int(last) - 1}": "verdict clause",
        f"**rows:** {len(rows)} annual reports, {first}–{last}": "rows fact",
        f"**ransomware complaints by year:** {line}": "ransomware by-year",
        f"**ransomware losses:** {millions(losses[last])} in {last} against "
        f"{millions(losses[str(int(last) - 1)])} in {int(last) - 1}; the "
        f"largest year is {peak} at {millions(losses[peak])}":
            "ransomware losses fact",
        f"**ransomware share of losses:** {share:.1%} of all reported losses "
        f"over {first}–{last}": "share fact",
        f"**total losses:** {billions(totals[last])} in {last} against "
        f"{billions(totals[first])} in {first}": "total losses fact",
        f"**complaints:** {int(by[biggest]['complaints']):,} in {biggest}, "
        "the most of any year here": "complaints fact",
    }
    failures = missing(prose(HERE), claims)
    # Each losses_as_stated string is the report's own wording; the parsed
    # number must be the one that wording states, or the CSV disagrees with
    # its own provenance column.
    for row in rows:
        stated = row["losses_as_stated"].replace(",", "")
        dollars = int(row["losses_usd"])
        if (f"{dollars}" not in stated
                and f"{dollars / 1e9:g} billion".lower() not in stated.lower()):
            failures.append(f"{row['year']}: losses_usd {dollars} is not what "
                            f"losses_as_stated says: {row['losses_as_stated']!r}")
    return report(failures)


if __name__ == "__main__":
    raise SystemExit(main())
