"""`toolkit locations` — clip -> location tagging, country mapping, interview rollup, extras.

Pipeline: tag (LLM, demo-first) -> map (regions down to countries) -> rollup (hybrid interview
tags). Extras: thresholds (rollover decision aid), annotate (re-render the review HTML), survey
(optional offline NER overview).
"""
from .annotate import annotate_locations
from .map import run_locations_map
from .rollup import run_locations_rollup
from .survey import run_locations_survey
from .tag import preview_call, run_locations_tag
from .thresholds_aid import run_locations_thresholds

__all__ = ["annotate_locations", "preview_call", "run_locations_map", "run_locations_rollup",
           "run_locations_survey", "run_locations_tag", "run_locations_thresholds"]
