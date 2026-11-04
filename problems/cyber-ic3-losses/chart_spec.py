"""Interactive charts for this folder's docs page.

tools/build_docs.py loads this module and embeds the Vega-Lite specs
``charts(slug)`` returns into the page rendered from the README.

Built from stacked_bars directly rather than split_series, whose caption
announces a partial final year: every IC3 row is a complete year.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lib.palette import VENDOR  # noqa: E402
from lib.vega import SEVERITY_RAMP, load, stacked_bars  # noqa: E402

CSV = "ic3-by-year.csv"
CAPTION = "Each bar is the figure one annual report states for its own year."


def charts(slug: str):
    rows = load(slug, CSV)
    return [
        ("Ransomware complaints",
         stacked_bars(rows, "year",
                      {"ransomware_complaints": "ransomware complaints"},
                      {"ransomware complaints": SEVERITY_RAMP[2]},
                      y_title="Ransomware complaints to IC3"),
         CAPTION),
        ("Reported losses",
         stacked_bars(rows, "year",
                      {"losses_usd": "all crime types"},
                      {"all crime types": VENDOR},
                      y_title="Reported losses (US dollars)"),
         CAPTION + " Ransomware losses, a fraction of a percent of these, "
         "are in the CSV's ransomware_losses_usd column."),
    ]
