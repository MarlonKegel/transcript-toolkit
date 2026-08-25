"""Transcripts that were never SYNC'd — the folder they go in, and what is in it.

It sits under the transcript list on the Workspace page, folded away, because for most projects
it never applies. It used to live on the Summarize page and to carry its own import and its own
demo, back when a summary was the only thing that could be made from a transcript with no
timestamps. That is no longer true: a clip is a run of paragraphs, and every transcript has
paragraph numbers, so these go through the whole pipeline with the rest. What they do not have
is times, and their clips show a paragraph range where the others show a start and an end.

So there is nothing here to run. Dropping a file in is what this is for; the Import button above
reads both folders, and every step page then treats these interviews like any other.
"""
from __future__ import annotations

from nicegui import ui

from ...errors import ToolkitError
from .. import content, workspaces
from ..context import CONTEXT
from .common import transcript_upload

HREF = "/workspace"

FOLDER_NOTE = ("Put a transcript here only when it has no timestamps and never will. One that "
               "should have them belongs in the transcripts folder above, where a missing "
               "timestamp is reported rather than accepted.")


def unsynced_section(refresh) -> None:
    """The fold. `refresh` redraws the transcript list after a drop, so a new file appears in
    both places at once."""
    project = CONTEXT.require_project()
    with ui.expansion(content.UNSYNCED_TITLE, icon="schedule").classes("w-full"):
        for paragraph in content.UNSYNCED_BLURB.split("\n\n"):
            ui.label(paragraph).classes("text-sm opacity-80 max-w-2xl")

        @ui.refreshable
        def listing() -> None:
            _listing(project)

        listing()

        def dropped() -> None:
            listing.refresh()
            refresh()

        transcript_upload(project, dropped, unsynced=True,
                          label="Drop transcripts that were never SYNC'd here",
                          next_move="Click Import above to read them in.",
                          note=f"They are copied into {project.unsynced_dir}. {FOLDER_NOTE}")


def _listing(project) -> None:
    """What is in the folder, file by file: did my drop land, and has it been read in yet?"""
    from ...steps.import_ import interview_rows

    files = workspaces.unsynced_transcript_rows(project)
    if not files:
        return
    try:
        facts = {r["interview_id"]: r for r in interview_rows(project)}
    except ToolkitError:
        facts = {}

    waiting = [f for f in files if not f["imported"]]
    headline = f"{len(files)} transcript{'s' if len(files) != 1 else ''}"
    headline += (f" · {len(waiting)} not read in yet — use Import above" if waiting
                 else " · all read in")
    ui.label(headline).classes("text-sm font-medium mt-2")

    with ui.row().classes("w-full items-center gap-2 px-1 text-xs opacity-60 font-medium"):
        ui.label("File").classes("grow")
        ui.label("Narrator").classes("w-40")
        ui.label("Words").classes("w-24 text-right")
    with ui.column().classes("w-full gap-0"):
        for f in files:
            _row(f, facts.get(f["interview_id"]))


def _row(row: dict, facts: dict | None) -> None:
    done = row["imported"]
    with ui.row().classes("items-center gap-2 w-full py-1 tk-row"):
        ui.icon("check_circle" if done else "schedule") \
            .classes("tk-good" if done else "tk-caution").props("size=1rem")
        with ui.column().classes("gap-0 grow min-w-0"):
            ui.label(row["filename"]).classes("text-xs font-mono truncate")
            if not done:
                ui.label("changed — import again" if row.get("changed")
                         else "not read in yet").classes("text-xs tk-caution")
        if facts:
            sessions = f" · {facts['sessions']} sessions" if facts["sessions"] > 1 else ""
            ui.label(facts["narrator"] + sessions).classes("text-xs opacity-70 w-40 truncate")
            ui.label(f"{facts['words']:,}").classes("text-xs opacity-70 w-24 text-right")
        else:
            ui.label("").classes("w-40")
            ui.label("").classes("w-24")
