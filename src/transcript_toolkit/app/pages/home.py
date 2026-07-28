"""The dashboard: where the project stands, and the one thing to do next."""
from __future__ import annotations

from nicegui import ui

from ...errors import ToolkitError
from .. import content
from ..context import CONTEXT
from ..workspaces import has_api_key, transcript_count
from .common import guard, section, shell


def _ran_fully(status: dict, step: content.Step, set_name: str | None) -> bool:
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


def _step_state(status: dict, step: content.Step, set_name: str | None) -> tuple[str, str]:
    """(word, colour) for one step, read off `toolkit status`."""
    try:
        key = content.step_key(step, set_name)
    except ValueError:
        return "no topic list yet", "grey"
    record = status["steps"].get(key, {})
    if record.get("full"):
        return "run on everything", "green"
    if step.deliverable in {d.split(":")[0] for d in status["deliverables"]}:
        return "partly run", "teal"
    if record.get("demo"):
        return "demo reviewed", "blue"
    return "not started", "grey"


def next_action(status: dict, project) -> tuple[str, str, str]:
    """(what to do, why, where). The demo-first workflow is the navigation: this is just it,
    read back to the user one step at a time."""
    if not has_api_key(project):
        return ("Add your OpenAI key", "Every step calls the API, so nothing runs without it.",
                "/workspace")
    if transcript_count(project) == 0:
        return ("Add your transcripts", "Drop the .docx files into the workspace to begin.",
                "/workspace")
    if not status["imported"]:
        return ("Import the transcripts", "Turn the .docx files into the dataset every step "
                "reads.", "/workspace")
    if status.get("import_stale"):
        return ("Import again", "The transcripts changed since the last import.", "/workspace")
    sets = _topic_sets_or_empty()
    for step in content.STEPS:
        set_name = sets[0] if (step.per_set and sets) else None
        if not _ran_fully(status, step, set_name):
            return (f"Run {step.title.lower()}", step.blurb, f"/step/{step.slug}")
    return ("Build the spreadsheet", "Every step has run — export what you have.", "/export")


def _topic_sets_or_empty() -> list[str]:
    try:
        return CONTEXT.topic_sets()
    except ToolkitError:
        return []


def home() -> None:
    with shell("/"):
        project = CONTEXT.project
        if project is None:
            return
        try:
            status = CONTEXT.status()
            sets = CONTEXT.topic_sets()
        except ToolkitError as e:
            guard(e)
            return

        title, why, href = next_action(status, project)
        with ui.card().classes("w-full bg-primary text-white"):
            ui.label("Next").classes("text-xs uppercase opacity-70")
            ui.label(title).classes("text-2xl font-medium")
            ui.label(why).classes("text-sm opacity-90")
            ui.button("Go", icon="arrow_forward", on_click=lambda: ui.navigate.to(href)) \
                .props("outline color=white dense").classes("mt-1 self-start")

        section("The pipeline", "Each step is demo-first: try it on a few interviews, read the "
                                "result, then run the whole corpus.")
        with ui.column().classes("w-full gap-2"):
            for step in content.STEPS:
                set_name = sets[0] if (step.per_set and sets) else None
                word, colour = _step_state(status, step, set_name)
                with ui.card().classes("w-full py-3"):
                    with ui.row().classes("items-center w-full gap-3"):
                        ui.label(str(step.order)).classes(
                            "text-sm opacity-40 w-4 text-right")
                        with ui.column().classes("gap-0 grow"):
                            ui.link(step.title, f"/step/{step.slug}") \
                                .classes("text-base font-medium no-underline")
                            ui.label(step.blurb).classes("text-xs opacity-70")
                        ui.chip(word, color=colour, text_color="white") \
                            .props("dense square").classes("text-xs")

        section("This workspace")
        with ui.card().classes("w-full"):
            with ui.grid(columns=2).classes("gap-x-8 gap-y-1 text-sm"):
                ui.label("Folder").classes("opacity-60")
                ui.label(str(project.root))
                ui.label("Transcripts").classes("opacity-60")
                ui.label(f"{status['docx_files']} .docx"
                         + ("" if status["imported"] else "  (not imported yet)"))
                ui.label("Topic lists").classes("opacity-60")
                ui.label(", ".join(sets) if sets else "none yet — add one on the Topics page")
                ui.label("Ready to export").classes("opacity-60")
                ui.label(", ".join(status["deliverables"]) or "nothing yet")


def register() -> None:
    ui.page("/", title="Transcript Toolkit")(home)
