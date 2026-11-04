"""Interactive charts for this folder's docs page.

tools/build_docs.py loads this module and embeds the Vega-Lite specs
``charts(slug)`` returns into the page rendered from the README.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lib.vega import AI, HUMAN, HUMAN_SOFT, periodic_split_series  # noqa: E402


charts = periodic_split_series(
    "exoplanets-by-quarter.csv", "quarter",
    {"other": "everything else",
     "archival_other": "archival Kepler/K2, other methods",
     "ai_paper": "paper states a machine-learning method"},
    {"everything else": HUMAN,
     "archival Kepler/K2, other methods": HUMAN_SOFT,
     "paper states a machine-learning method": AI},
    "Planets confirmed")
