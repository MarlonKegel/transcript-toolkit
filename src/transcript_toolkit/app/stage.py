"""Where a project has got to.

The demo-first workflow is the navigation: at any moment there is one sensible next thing to do,
and both the projects list and the workspace page are that answer read back. Everything here
comes from `toolkit status` — the same picture the command line prints.
"""
from __future__ import annotations

from ..errors import ToolkitError
from ..project import Project
from . import content, workspaces

NOT_STARTED = "not started"


def ran_fully(status: dict, step: content.Step, set_name: str | None) -> bool:
    """Whether the step has been run over everything.

    Read from the run the step recorded, not from a file on disk: `locations tag` records its
    full run, but the file `toolkit status` counts as the locations deliverable is written by
    `locations map`, one command later. Judging by the file alone would keep telling someone
    to run the expensive step they just paid for.
    """
    try:
        key = content.step_key(step, set_name)
    except ValueError:
        return False
    return bool(status["steps"].get(key, {}).get("full"))


def step_state(status: dict, step: content.Step, set_name: str | None) -> tuple[str, str]:
    """(word, colour) for one step, read off `toolkit status`."""
    try:
        key = content.step_key(step, set_name)
    except ValueError:
        return "no topic list yet", "grey"
    record = status["steps"].get(key, {})
    if record.get("full"):
        return "run on everything", "positive"
    if step.deliverable in {d.split(":")[0] for d in status["deliverables"]}:
        return "partly run", "secondary"
    if record.get("demo"):
        return "demo reviewed", "primary"
    return NOT_STARTED, "grey"


def next_action(status: dict, project: Project, sets: list[str]) -> tuple[str, str, str]:
    """(what to do, why, where)."""
    if not workspaces.has_api_key(project):
        return ("Add your OpenAI key", "Every step calls the API, so nothing runs without it.",
                "/workspace")
    if status["docx_files"] == 0:
        return ("Add your transcripts", "Drop the .docx files into the workspace to begin.",
                "/workspace")
    if not status["imported"]:
        return ("Import the transcripts", "Turn the .docx files into the dataset every step "
                "reads.", "/workspace")
    if status.get("import_stale"):
        return ("Import again", "The transcripts changed since the last import.", "/workspace")
    for step in content.STEPS:
        set_name = sets[0] if (step.per_set and sets) else None
        if not ran_fully(status, step, set_name):
            return (f"Run {step.title.lower()}", step.blurb, f"/step/{step.slug}")
    return ("Build the spreadsheet", "Every step has run — export what you have.", "/export")


def steps_done(status: dict, sets: list[str]) -> int:
    return sum(1 for step in content.STEPS
               if ran_fully(status, step, sets[0] if (step.per_set and sets) else None))


def summary(path: str) -> dict:
    """One project, for the list of them: what it is called, where it has got to, and what to do
    next. A folder that has been renamed or thrown away is reported as such rather than left out
    — somebody has to be told which of their projects the app can no longer find.
    """
    from ..core.config import load_root_config
    from ..project import find_project
    from ..steps.status import gather_status
    from ..steps.topics.taxonomy import available_sets

    try:
        project = find_project(path)
        status = gather_status(project)
        topics = load_root_config(project).get("topics") or {}
        sets = available_sets(project, topics)
    except ToolkitError as e:
        return {"path": path, "found": False, "trouble": str(e)}

    done = steps_done(status, sets)
    what, why, href = next_action(status, project, sets)
    return {
        "path": path,
        "found": True,
        "name": status["name"],
        "folder": project.root.name,
        "transcripts": status["docx_files"],
        "imported": status["imported"],
        "steps_done": done,
        "steps_total": len(content.STEPS),
        "exportable": status["deliverables"],
        "next": what,
        "why": why,
        "href": href,
    }


def all_projects() -> list[dict]:
    """Every project the app has opened, most recent first."""
    return [summary(entry["path"]) for entry in workspaces.load_registry()]
