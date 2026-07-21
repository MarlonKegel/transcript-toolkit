"""`toolkit topics` — deductive topic tagging against user-supplied topic sets.

Sub-steps: tag (clip scores, demo-first), rollup (clip -> interview tags), thresholds
(rollup decision aid), annotate (per-interview review md), plus a call preview.
"""
from .annotate import annotate_topics
from .rollup import run_topics_rollup
from .tag import preview_call, run_topics_tag
from .taxonomy import TopicSet, load_topic_set
from .thresholds_aid import run_topics_thresholds

__all__ = [
    "TopicSet",
    "annotate_topics",
    "load_topic_set",
    "preview_call",
    "run_topics_rollup",
    "run_topics_tag",
    "run_topics_thresholds",
]
