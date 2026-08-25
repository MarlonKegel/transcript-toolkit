"""`toolkit status` — workspace overview: corpus, per-step demo/run state, what export includes."""
from __future__ import annotations

import json

from ..core.config import load_root_config, project_name
from ..core.prompts import prompt_files
from ..project import Project
from ..state import load_state


def _corpus(project: Project) -> dict:
    # Both transcript folders are the collection: one import reads them together into one
    # dataset, so both are counted here and either one being newer than the dataset means
    # there is an import to run.
    from .import_ import find_docx_files, find_unsynced_files

    timed = find_docx_files(project)
    untimed = find_unsynced_files(project)
    imported = project.paragraphs_path.exists()
    stale = False
    if imported and (timed or untimed):
        newest = max(p.stat().st_mtime for p in [*timed, *untimed])
        stale = newest > project.paragraphs_path.stat().st_mtime
    return {"docx_files": len(timed) + len(untimed), "imported": imported, "import_stale": stale,
            "unsynced_files": len(untimed)}


def _deliverables(project: Project) -> list[str]:
    out = project.outputs_dir
    present = []
    if (out / "clips" / "clips.parquet").exists():
        present.append("clips")
    if (out / "labels" / "labels.parquet").exists():
        present.append("labels")
    if (out / "summaries" / "summaries.parquet").exists():
        present.append("summaries")
    sets = ((load_root_config(project).get("topics") or {}).get("sets") or {})
    for s in sets:
        if (out / "topics" / f"{s}_clip_topics_wide.parquet").exists():
            present.append(f"topics:{s}")
    if (out / "locations" / "clip_countries.parquet").exists():
        present.append("locations")
    return present


def gather_status(project: Project) -> dict:
    return {
        "workspace": str(project.root),
        "name": project_name(project),
        **_corpus(project),
        "steps": load_state(project)["steps"],
        "deliverables": _deliverables(project),
        "prompts": prompt_files(project),
    }


FRESH_WORDS = {
    ("current", "current"): "up to date",
    ("current", "partial"): "more to run: the collection has grown",
    ("current", "stale"): "run it on everything",
    ("current", "none"): "run it on everything",
    ("stale", "current"): "demo it again: the prompt or settings changed",
    ("stale", "stale"): "demo it again: the prompt or settings changed",
    ("stale", "partial"): "demo it again: the prompt or settings changed",
    ("stale", "none"): "demo it again: the prompt or settings changed",
}


def _freshness(project: Project, step_key: str) -> str:
    """Whether running this step again would do anything — the same answer the app greys its
    buttons on (steps/freshness.py), said in words here."""
    from .freshness import freshness

    step, _, set_name = step_key.partition(":")
    state = freshness(project, step, set_name or None)
    return FRESH_WORDS.get((state["demo"], state["full"]), "demo it")


def run_status(project: Project, as_json: bool = False) -> None:
    info = gather_status(project)
    if as_json:
        print(json.dumps(info, indent=2))
        return
    print(f"Workspace: {info['workspace']}  ({info['name']})")
    imp = "" if info["imported"] else "   (not yet imported — run `toolkit import`)"
    if info.get("import_stale"):
        imp = "   (transcripts changed since import — re-run `toolkit import`)"
    print(f"Transcripts in data/: {info['docx_files']} .docx{imp}")
    if info.get("unsynced_files"):
        print(f"  of those, {info['unsynced_files']} in data/unsynced/ were never SYNC'd: they "
              f"go through every step, but their clips carry no times")

    if info["steps"]:
        print("\nSteps:")
        for step_key, rec in sorted(info["steps"].items()):
            demo = rec.get("demo")
            full = rec.get("full")
            demo_txt = f"demo {demo['at'][:10]}" if demo else "no demo"
            full_txt = (f"full {full['at'][:10]} ({full['model']}, {full['n_units']})"
                        if full else "no full run")
            print(f"  {step_key:<16} {demo_txt:<20} {full_txt:<38} {_freshness(project, step_key)}")

    print("\nPrompts (edit these in prompts/, or restore one with "
          "`toolkit init --reset-prompt NAME`):")
    for step, name in info["prompts"].items():
        print(f"  {step:<16} prompts/{name}")

    print(f"\nExport would include: {', '.join(info['deliverables']) or '(nothing yet — run some steps)'}")
