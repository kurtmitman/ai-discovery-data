#!/usr/bin/env python3
"""Rebuild this folder's three CSVs from the HHS Office for Civil Rights breach portal.

Run: python3 problems/cyber-hhs-breaches/fetch.py

The portal lists every breach of unsecured protected health information that
affected 500 or more people and was reported to HHS, in two listings: cases
reported in the last 24 months and still under investigation, and an archive
of resolved or older reports. Together they are the full record back to
October 2009. Each listing has an "Export as CSV" control.

The portal is a JavaServer Faces application, so there is no export URL to GET:
the export is a form postback carrying the page's view state, and the archive
is a second tab reached by a tab-change request. This script replays those
three steps with curl and a cookie jar. The controls are found by their labels
("View HIPAA Breach Reports", the CSV icon, the archive tab), not by the
generated `j_idt` identifiers, which change when the application is redeployed.

Three CSVs come out:

- hhs-breaches.csv: one row per breach, minus the free-text web description.
- hhs-breaches-by-quarter.csv and hhs-breaches-by-year.csv: counts and people
  affected, split into Hacking/IT Incident and every other breach type.

Rows submitted after lib/dates.py's AS_OF_DATE are dropped, so a refetch
reproduces the committed window.
"""

from __future__ import annotations

import csv
import io
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from lib.dates import AS_OF_DATE  # noqa: E402
from lib.table import write_csv  # noqa: E402

BASE = "https://ocrportal.hhs.gov/ocr/breach"
FRONT = f"{BASE}/breach_frontpage.jsf"
REPORT = f"{BASE}/breach_report_hip.jsf"
FIRST_YEAR = 2009
HACKING = "Hacking/IT Incident"
# The export's header names the two panel columns by Java object identity
# rather than by title; these are the columns by position.
COLUMNS = ["entity", "state", "entity_type", "individuals_affected",
           "submitted", "breach_type", "location", "business_associate",
           "description"]
TITLED = {1: "State", 2: "Covered Entity Type", 3: "Individuals Affected",
          4: "Breach Submission Date", 5: "Type of Breach",
          6: "Location of Breached Information", 8: "Web Description"}


class Portal:
    """A curl session against the portal: one cookie jar, the latest page."""

    def __init__(self, jar: Path) -> None:
        self.jar = jar
        self.page = ""
        self.tabs = ""

    def request(self, url: str, form: dict[str, str] | None = None, *,
                multipart: bool = True, headers: dict[str, str] | None = None) -> str:
        command = ["curl", "--fail", "--silent", "--show-error", "--location",
                   "--max-time", "300", "--cookie", str(self.jar),
                   "--cookie-jar", str(self.jar)]
        for name, value in (headers or {}).items():
            command += ["--header", f"{name}: {value}"]
        for name, value in (form or {}).items():
            if multipart:
                # --form-string: a value starting with @ or < is literal text.
                command += ["--form-string", f"{name}={value}"]
            else:
                command += ["--data-urlencode", f"{name}={value}"]
        result = subprocess.run(command + [url], capture_output=True)
        if result.returncode != 0:
            raise SystemExit(f"{url}: {result.stderr.decode(errors='replace').strip()}")
        return result.stdout.decode("utf-8", errors="replace")

    def view_state(self) -> str:
        found = re.search(r'name="javax\.faces\.ViewState"[^>]*value="([^"]+)"',
                          self.page) or re.search(
            r'ViewState:\d+"><!\[CDATA\[([^\]]+)\]\]>', self.page)
        if not found:
            raise SystemExit("portal page carries no view state; layout changed")
        return found.group(1)

    def control(self, pattern: str, what: str) -> str:
        found = re.search(pattern, self.page)
        if not found:
            raise SystemExit(f"portal page has no {what}; layout changed")
        return found.group(1)

    def open_report(self) -> None:
        self.page = self.request(FRONT)
        link = self.control(
            r"\{'(ocrForm:j_idt\d+)':'\1'\},''\);return false\">"
            r"\s*View HIPAA Breach Reports", "breach-report link")
        self.page = self.request(FRONT, {
            "ocrForm": "ocrForm", link: link,
            "javax.faces.ViewState": self.view_state()})
        # The tab-change response only re-renders the listing, so the tab
        # container's identifier is read once, here.
        self.tabs = self.control(r'PrimeFaces\.cw\("TabView","[^"]*",\{id:"([^"]+)"',
                                 "tab view")

    def export_csv(self, active_index: str) -> str:
        button = self.control(
            r"\{'(ocrForm:j_idt\d+)':'\1'\},''\);return false\">"
            r'<img id="ocrForm:j_idt\d+" src="/ocr/images/icons/csv\.png',
            "CSV export control")
        return self.request(REPORT, {
            "ocrForm": "ocrForm", f"{self.tabs}_activeIndex": active_index,
            button: button, "javax.faces.ViewState": self.view_state()})

    def open_archive(self) -> None:
        tabs = self.tabs
        archive = self.control(r'href="#(ocrForm:j_idt\d+:archiveTab)"',
                               "archive tab")
        self.page = self.request(REPORT, {
            "javax.faces.partial.ajax": "true",
            "javax.faces.source": tabs,
            "javax.faces.partial.execute": tabs,
            "javax.faces.partial.render": "ocrForm:breachReports ocrForm:results",
            "javax.faces.behavior.event": "tabChange",
            "javax.faces.partial.event": "tabChange",
            f"{tabs}_newTab": archive,
            f"{tabs}_tabindex": "1",
            "ocrForm": "ocrForm",
            f"{tabs}_activeIndex": "1",
            "javax.faces.ViewState": self.view_state(),
        }, multipart=False, headers={"Faces-Request": "partial/ajax"})
        if "This page archives" not in self.page:
            raise SystemExit("tab change did not reach the archive listing")


def parse(text: str, listing: str) -> list[dict]:
    rows = list(csv.reader(io.StringIO(text)))
    header, body = rows[0], rows[1:]
    for index, name in TITLED.items():
        if header[index] != name:
            raise SystemExit(f"{listing} export column {index} is {header[index]!r}, "
                             f"expected {name!r}")
    out = []
    for raw in body:
        if not any(cell.strip() for cell in raw):
            continue
        record = dict(zip(COLUMNS, raw))
        submitted = datetime.strptime(record["submitted"], "%m/%d/%Y").date()
        out.append({
            "submitted": submitted.isoformat(),
            "entity": record["entity"].strip(),
            "state": record["state"].strip(),
            "entity_type": record["entity_type"].strip(),
            "individuals_affected": int(record["individuals_affected"] or 0),
            "breach_type": record["breach_type"].strip(),
            "location": record["location"].strip(),
            "business_associate": record["business_associate"].strip(),
            "listing": listing,
        })
    if not out:
        raise SystemExit(f"{listing} listing exported no rows")
    return out


def rollup(rows: list[dict], key, labels: list[str], through: str) -> list[dict]:
    totals: dict[str, dict] = defaultdict(lambda: defaultdict(int))
    for row in rows:
        bucket = totals[key(row["submitted"])]
        hacking = HACKING in row["breach_type"]
        bucket["breaches"] += 1
        bucket["hacking" if hacking else "other"] += 1
        bucket["individuals_affected"] += row["individuals_affected"]
        bucket["hacking_individuals" if hacking else "other_individuals"] += \
            row["individuals_affected"]
    last = key(through)
    return [
        {
            "period": label,
            "breaches": totals[label]["breaches"],
            "hacking": totals[label]["hacking"],
            "other": totals[label]["other"],
            "individuals_affected": totals[label]["individuals_affected"],
            "hacking_individuals": totals[label]["hacking_individuals"],
            "other_individuals": totals[label]["other_individuals"],
            "partial": "yes" if label == last else "no",
            "data_through": through if label == last else "",
        }
        for label in labels
    ]


def quarter_of(day: str) -> str:
    return f"{day[:4]}-Q{(int(day[5:7]) - 1) // 3 + 1}"


def main() -> None:
    with tempfile.TemporaryDirectory() as scratch:
        portal = Portal(Path(scratch) / "cookies.txt")
        portal.open_report()
        current = parse(portal.export_csv("0"), "current")
        portal.open_archive()
        archive = parse(portal.export_csv("1"), "archive")
    seen = {(r["entity"], r["submitted"], r["individuals_affected"]) for r in current}
    overlap = [r for r in archive
               if (r["entity"], r["submitted"], r["individuals_affected"]) in seen]
    if overlap:
        raise SystemExit(f"{len(overlap)} breaches appear in both listings")
    rows = [r for r in current + archive
            if r["submitted"] <= AS_OF_DATE.isoformat()]
    rows.sort(key=lambda r: (r["submitted"], r["entity"], r["individuals_affected"]))
    through = rows[-1]["submitted"]
    last_year = int(through[:4])
    years = [str(y) for y in range(FIRST_YEAR, last_year + 1)]
    quarters = [f"{y}-Q{q}" for y in range(FIRST_YEAR, last_year + 1)
                for q in range(1, 5) if f"{y}-Q{q}" <= quarter_of(through)]
    quarters = quarters[quarters.index(quarter_of(rows[0]["submitted"])):]
    annual = rollup(rows, lambda d: d[:4], years, through)
    quarterly = rollup(rows, quarter_of, quarters, through)
    for table, period in ((annual, "year"), (quarterly, "quarter")):
        for row in table:
            row[period] = row.pop("period")
            row[f"partial_{period}"] = row.pop("partial")
            row["data_through"] = row.pop("data_through")
    print(f"HHS breaches: {len(current)} current + {len(archive)} archive; "
          f"{len(rows)} kept through {through} (AS_OF {AS_OF_DATE})")
    write_csv(HERE / "hhs-breaches.csv", rows)
    fields = ["breaches", "hacking", "other", "individuals_affected",
              "hacking_individuals", "other_individuals"]
    write_csv(HERE / "hhs-breaches-by-year.csv", annual,
              ["year", *fields, "partial_year", "data_through"])
    write_csv(HERE / "hhs-breaches-by-quarter.csv", quarterly,
              ["quarter", *fields, "partial_quarter", "data_through"])


if __name__ == "__main__":
    main()
