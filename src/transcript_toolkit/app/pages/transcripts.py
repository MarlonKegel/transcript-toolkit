"""The transcripts in a project: one list, showing what is there and what the toolkit read.

Before this there were two lists — the files in the folder, and then the same interviews again
from the dataset. One row per transcript carries both: whether it has been imported, how much of
it there is, whose it is, and whether it is timestamped the way the clip times want.
"""
from __future__ import annotations

from nicegui import ui

from ...errors import ToolkitError
from .. import content, theme, workspaces
from ..context import CONTEXT
from .common import guard, info, inline_state, launch, section, transcript_upload
from .settings_form import settings_form

HREF = "/workspace"

TIMESTAMP_NOTE = ("Every paragraph should carry its own [HH:MM:SS]. Where only the speaker turns "
                  "are timestamped the pipeline still runs, but a clip's start and end times are "
                  "as coarse as the turn it falls in.")


def transcripts_section(refresh) -> None:
    project = CONTEXT.require_project()
    section("Transcripts", "Word files of SYNC'd (timestamped) transcripts — one per interview, "
                           "or one per session.")
    with ui.card().classes("w-full"):

        @ui.refreshable
        def listing() -> None:
            _listing(project)

        listing()

        transcript_upload(project, listing.refresh, unsynced=False,
                          label="Drop .docx files here",
                          next_move="Click Import to read them in.",
                          note=f"They are copied into {project.data_dir}")

        with ui.row().classes("gap-2 items-center mt-2"):
            ui.button("Import", icon="play_arrow", on_click=_import_click).props("dense")
            inline_state("Import")
            ui.label("Reads the .docx files into the dataset every step works from. "
                     "Run it again whenever you add or change a transcript.") \
                .classes("text-xs opacity-70 max-w-lg")

        with ui.expansion("How transcripts are read", icon="tune").classes("w-full"):
            ui.label("These decide who counts as the interviewer and how a filename becomes an "
                     "interview id. Change one and import again.").classes("text-xs opacity-70")
            settings_form("import", on_saved=refresh, note=False,
                          save_label="Save how transcripts are read")


def _listing(project) -> None:
    """What is in the folder, joined to what the dataset knows about it."""
    from ...steps.import_ import dataset_summary, interview_rows

    files = workspaces.transcript_rows(project)
    if not files:
        ui.label("No transcripts yet — drop them in below.").classes("text-sm")
        return

    facts = {row["interview_id"]: row for row in interview_rows(project)}
    waiting = [r for r in files if not r["imported"]]
    summary = dataset_summary(project) if project.paragraphs_path.exists() else None

    headline = f"{len(files)} transcript{'s' if len(files) != 1 else ''}"
    if summary:
        headline += (f" · {summary['n_paragraphs']:,} paragraphs · "
                     f"{summary['n_narrators']} narrator"
                     f"{'s' if summary['n_narrators'] != 1 else ''}")
    headline += f" · {len(waiting)} not imported yet" if waiting else " · all imported"
    ui.label(headline).classes("text-sm font-medium")

    rough = [r for r in facts.values() if not r["timestamps_ok"]]
    if rough:
        with ui.row().classes("items-center gap-1"):
            ui.label(f"{len(rough)} of them are timestamped on speaker turns only.") \
                .classes("text-xs tk-caution")
            info(TIMESTAMP_NOTE)

    with ui.row().classes("w-full items-center gap-2 px-1 text-xs opacity-60 font-medium"):
        ui.label("File").classes("grow")
        ui.label("Narrator").classes("w-40")
        ui.label("Paragraphs").classes("w-24 text-right")
    with ui.column().classes("w-full gap-0 overflow-auto").style(theme.LIST_HEIGHT):
        for row in files:
            _row(row, facts.get(row["interview_id"]))

    if summary:
        with ui.expansion("Who the speakers are", icon="record_voice_over").classes("w-full"):
            ui.label("If an interviewer shows up as the narrator, change the interviewer labels "
                     "below and import again.").classes("text-xs opacity-70")
            ui.table(columns=[{"name": "speaker_role", "label": "Role", "field": "speaker_role",
                               "align": "left"},
                              {"name": "speaker_label", "label": "As written in the transcript",
                               "field": "speaker_label", "align": "left"},
                              {"name": "n", "label": "Paragraphs", "field": "n",
                               "align": "right"}],
                     rows=summary["roles"], row_key="speaker_label") \
                .props("dense flat").classes("w-full")


def _row(row: dict, facts: dict | None) -> None:
    done = row["imported"]
    with ui.row().classes("items-center gap-2 w-full py-1 tk-row"):
        ui.icon("check_circle" if done else "schedule") \
            .classes("tk-good" if done else "tk-caution").props("size=1rem")
        with ui.column().classes("gap-0 grow min-w-0"):
            ui.label(row["filename"]).classes("text-xs font-mono truncate")
            if not done:
                ui.label("changed — import again" if row.get("changed")
                         else "not imported yet").classes("text-xs tk-caution")
        if facts:
            sessions = (f" · {facts['sessions']} sessions" if facts["sessions"] > 1 else "")
            ui.label(facts["narrator"] + sessions).classes("text-xs opacity-70 w-40 truncate")
            ui.label(f"{facts['paragraphs']:,}").classes("text-xs opacity-70 w-24 text-right")
            if not facts["timestamps_ok"]:
                ui.icon("schedule").classes("tk-caution").props("size=1rem") \
                    .tooltip(facts["timestamps"])
        else:
            ui.label("").classes("w-40")
            ui.label("").classes("w-24")


async def _import_click() -> None:
    """Import, unless there is nothing new to import — in which case say so instead of running
    a command that would look like it did nothing."""
    project = CONTEXT.require_project()
    if not workspaces.transcript_rows(project):
        guard(ToolkitError("There are no transcripts to import yet. Drop your .docx files in "
                           "the box above first."))
        return
    if workspaces.everything_imported(project):
        _already_imported_dialog()
        return
    await launch("Import", list(content.IMPORT.argv), HREF)


def _already_imported_dialog() -> None:
    with ui.dialog() as dialog, ui.card().classes("max-w-md"):
        ui.label("Everything is already imported").classes("text-lg font-medium")
        ui.label("All the transcripts in this project have been read in. To add more, drop "
                 "them in the box above and then click Import again.").classes("text-sm")
        ui.label("If you edited a transcript that is already here, import it again to pick up "
                 "the change.").classes("text-xs opacity-70")
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("OK", on_click=dialog.close).props("flat dense")

            async def anyway() -> None:
                dialog.close()
                await launch("Import", list(content.IMPORT.argv), HREF)

            ui.button("Import again anyway", on_click=anyway).props("dense")
    dialog.open()
