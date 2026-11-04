"""Interactive charts for this folder's docs page.

tools/build_docs.py loads this module and embeds the Vega-Lite specs
``charts(slug)`` returns into the page rendered from the README.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lib.vega import SEVERITY_RAMP, periodic_split_series  # noqa: E402


charts = periodic_split_series(
    "hhs-breaches-by-quarter.csv", "quarter",
    {"hacking": "Hacking/IT Incident", "other": "every other type"},
    {"Hacking/IT Incident": SEVERITY_RAMP[2],
     "every other type": SEVERITY_RAMP[0]},
    "Breaches of 500+ people")
