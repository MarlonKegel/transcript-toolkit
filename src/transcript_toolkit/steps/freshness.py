"""Whether running a step again would produce anything new.

A step records the fingerprint of every demo and every full run — the same `cache_key` over
model, reasoning and the exact instructions text that keys the per-call cache. So "has this
already run, and has anything changed since?" is answerable without calling anything: work out
what a run would fingerprint now, and compare.

The demo gate already uses this to refuse a full run behind a stale demo. Here it is the other
way round: a run that would send nothing new is a button worth greying out, with the reason
said rather than left to be discovered by pressing it.

Two things save this from being a lie. A run is only "done" while its output is still on disk —
delete a deliverable and re-running is repair, not waste. And a full run is only "done" while
the collection is the size it covered: import more transcripts and there is more to do, though
nothing about the instructions changed.
"""
from __future__ import annotations

from ..errors import ToolkitError
from ..project import Project
from ..state import load_state

NONE, STALE, CURRENT, PARTIAL = "none", "stale", "current", "partial"


def current_fingerprint(project: Project, step: str, set_name: str | None = None) -> str:
    """What a run of this step would fingerprint right now.

    Each step assembles its own instructions and hashes them in its `_context`; this calls the
    same function, so there is no second implementation to drift. No API calls — only the files
    a run would read.
    """
    if step == "clip":
        from .clip.run import _context
        return _context(project)[2]
    if step == "label":
        from .label.run import _context
        return _context(project)[2]
    if step == "summarize":
        from .summarize import _context
        return _context(project, None)[2]
    if step == "topics":
        from .topics.tag import _context
        return _context(project, set_name, None, False)[4]
    if step == "locations":
        from .locations.tag import _context
        return _context(project, False)[3]
    raise ToolkitError(f"No fingerprint for step {step!r}.")


def unit_count(project: Project, step: str, set_name: str | None = None) -> int:
    """How many things a full run would work through, counted the same way the step records it.

    It has to be the same way: `label` labels every clip but calls the model once per interview
    and records interviews, so counting its clips would leave a finished run reading as partial
    for ever. Interviews for clip, label and summarize; clips for topics and locations.
    """
    import pandas as pd

    if step == "clip":
        if not project.paragraphs_path.exists():
            return 0
        return int(pd.read_parquet(project.paragraphs_path,
                                   columns=["interview_id"])["interview_id"].nunique())
    if step == "summarize":
        from .summarize import _context
        return len(_context(project, None)[3])
    from ..core.tables import clips_path
    path = clips_path(project)
    if not path.exists():
        return 0
    if step == "label":
        return int(pd.read_parquet(path, columns=["interview_id"])["interview_id"].nunique())
    return len(pd.read_parquet(path, columns=["clip_id"]))


# What a full run of each step writes itself. Deliberately not `toolkit status`'s deliverable
# list: that reports `locations` once `clip_countries.parquet` exists, which `locations map`
# writes one command later. Judging a locations run by that file would call it undone right
# after it was paid for.
WRITES = {
    "clip": ["clips/clips.parquet"],
    "label": ["labels/labels.parquet"],
    "summarize": ["summaries/summaries.parquet"],
    "topics": ["topics/{set}_clip_topics_wide.parquet"],
    "locations": ["locations/clip_locations.parquet"],
}


def wrote_its_results(project: Project, step: str, set_name: str | None = None) -> bool:
    """Whether the step's own output is still on disk. Delete it and re-running is repair."""
    return all((project.outputs_dir / p.format(set=set_name or "")).exists()
               for p in WRITES.get(step, []))


def freshness(project: Project, step: str, set_name: str | None = None) -> dict:
    """What re-running this step would be worth: `demo` and `full` as none/stale/current, plus
    `partial` for a full run the collection has outgrown."""
    key = f"{step}:{set_name}" if set_name else step        # as the steps record it
    record = load_state(project)["steps"].get(key, {})
    try:
        now = current_fingerprint(project, step, set_name)
    except (ToolkitError, OSError, KeyError):
        # Nothing to compare against — a topic list that is gone, a prompt that will not read.
        # Say so by claiming nothing: every button stays live and the run reports the real error.
        return {"fingerprint": None, "demo": NONE, "full": NONE}

    demo = record.get("demo")
    full = record.get("full")
    return {"fingerprint": now,
            "demo": _demo_state(project, demo, now, step),
            "full": _full_state(project, full, now, step, set_name)}


# The steps whose demo runs on the interviews `toolkit sample` picked. Nothing about changing
# that choice touches the fingerprint — it is not part of the instructions — so a demo would go
# on reading as done over a set of interviews it never saw. Somebody who has just picked
# different interviews has said plainly that they want the demo run on those.
ON_THE_SAMPLE = ("clip", "label")


def _demo_state(project: Project, demo: dict | None, now: str, step: str) -> str:
    from pathlib import Path

    if not demo:
        return NONE
    if demo["fingerprint"] != now:
        return STALE
    if step in ON_THE_SAMPLE and _sample_changed_since(project, demo.get("at")):
        return STALE
    # A demo is only done while what it left to read is still there. `diag` is recorded as an
    # absolute path, so a project that has been moved reads as "not run" rather than as done
    # with nothing to show for it — and re-running a demo is cheap.
    diag = demo.get("diag")
    return CURRENT if not diag or Path(diag).exists() else NONE


def _sample_changed_since(project: Project, at: str | None) -> bool:
    from datetime import datetime, timezone

    path = project.demo_sample_path
    if not at or not path.exists():
        return False
    try:
        when = datetime.fromisoformat(at)
    except ValueError:
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    # A run record keeps whole seconds, so a demo started in the same second as the sample it
    # ran on looks a fraction older than it. The second of slack is that rounding, not a
    # tolerance for real edits: picking a new sample and re-drawing takes longer than that.
    return path.stat().st_mtime > when.timestamp() + 1


# The free, deterministic steps that come after tagging: what each one writes, and what it reads.
# They make no calls, so "would this do anything new?" is a question about files — the output has
# to be there and newer than everything that feeds it, config.yaml included. Any edit to config
# re-enables them, which is the harmless direction to be wrong in: offering a run that turns out
# to change nothing costs a second, and hiding one that was needed costs a wrong deliverable.
DERIVED = {
    ("topics", "rollup"): (["topics/{set}_interview_topics_wide.parquet"],
                           ["topics/{set}_clip_topics_wide.parquet"]),
    ("locations", "map"): (["locations/clip_countries.parquet"],
                           ["locations/clip_locations.parquet"]),
    ("locations", "rollup"): (["locations/interview_locations_wide.parquet"],
                              ["locations/clip_countries.parquet"]),
}

# Files these steps read that are not deliverables and are not config.yaml. Both locations moves
# turn a region into its countries, and the app now invites editing that table — after which
# both buttons would otherwise stay greyed out as done and the correction never be applied.
EDITABLE_INPUTS = {
    ("locations", "map"): ("locations", "region_map_file"),
    ("locations", "rollup"): ("locations", "region_map_file"),
}


def _editable_input(project: Project, step: str, action: str):
    """The path of that file, or None when config cannot say where it is."""
    named = EDITABLE_INPUTS.get((step, action))
    if named is None:
        return None
    from ..core.config import load_step_config

    try:
        where = load_step_config(project, named[0]).get(named[1])
    except (ToolkitError, OSError, KeyError):
        return None
    return project.root / where if where else None


def derived_state(project: Project, step: str, action: str, set_name: str | None = None) -> str:
    """CURRENT when this action's output is on disk and newer than everything it reads."""
    paths = DERIVED.get((step, action))
    if paths is None:
        return NONE
    outputs, inputs = ([project.outputs_dir / p.format(set=set_name or "") for p in group]
                       for group in paths)
    if not all(p.exists() for p in outputs):
        return NONE
    watched = [*inputs, project.config_path, _editable_input(project, step, action)]
    newest_input = max((p.stat().st_mtime for p in watched if p and p.exists()), default=0.0)
    return CURRENT if min(p.stat().st_mtime for p in outputs) >= newest_input else STALE


def _full_state(project: Project, full: dict | None, now: str, step: str,
                set_name: str | None) -> str:
    if not full:
        return NONE
    if full["fingerprint"] != now:
        return STALE
    if not wrote_its_results(project, step, set_name):
        return NONE
    try:
        units = unit_count(project, step, set_name)
    except (ToolkitError, OSError, KeyError):
        return CURRENT
    return PARTIAL if units > int(full.get("n_units") or 0) else CURRENT
