"""Summarizing transcripts that were never SYNC'd — the one way in for a file with no timestamps.

It lives on the Summarize page and nowhere else, and it is folded away until it is asked for,
because for most projects it never applies. The reason it is confined here is not a rule about
tidiness: a clip is a span between two times, so a transcript with no times cannot be clipped,
and everything except the summary hangs off the clips.

The same three moves as any other step — read them in, try it, run it — over a folder of its own
and a demo of its own. Every button is a real `toolkit` command (`content.py`), same as the rest
of the app.
"""
from __future__ import annotations

from nicegui import ui

from ...errors import ToolkitError
from .. import content, workspaces
from ..context import CONTEXT
from .common import guard, inline_state, launch, run_status

HREF = "/step/summarize"

FOLDER_NOTE = ("Nothing here reaches the collection: importing the transcripts does not read "
               "this folder, so these stay out of the clips, the labels and the tags.")


def unsynced_section(refresh) -> None:
    """The whole thing, folded away. `refresh` redraws the Summarize page after a run."""
    project = CONTEXT.require_project()
    with ui.expansion(content.UNSYNCED_TITLE, icon="schedule").classes("w-full"):
        for paragraph in content.UNSYNCED_BLURB.split("\n\n"):
            ui.label(paragraph).classes("text-sm opacity-80 max-w-2xl")

        @ui.refreshable
        def listing() -> None:
            _listing(project)

        # Built once and never rebuilt by an upload: redrawing the box while files are still
        # arriving drops most of a multi-file drop on the floor (see pages/transcripts.py).
        async def receive(e) -> None:
            added, refused = [], []
            for upload in e.files:
                try:
                    workspaces.add_transcript(project, upload.name, await upload.read(),
                                              unsynced=True)
                    added.append(upload.name)
                except ToolkitError as err:
                    refused.append(str(err))
            listing.refresh()
            if added:
                ui.notify(f"Added {len(added)} transcript{'s' if len(added) != 1 else ''}. "
                          f"Read them in next.", type="positive")
            for message in refused:
                guard(ToolkitError(message))

        ui.upload(on_multi_upload=receive, multiple=True, auto_upload=True,
                  label="Drop transcripts that were never SYNC'd here") \
            .props("accept=.docx flat bordered").classes("w-full")
        ui.label(f"They are copied into {project.unsynced_dir}. {FOLDER_NOTE}") \
            .classes("text-xs opacity-60 max-w-2xl")

        listing()
        _flow(project, refresh)


def _listing(project) -> None:
    """What is in the folder, and what the toolkit has made of it."""
    from ...steps.import_ import unsynced_interview_rows

    files = workspaces.unsynced_files(project)
    if not files:
        return
    try:
        rows = unsynced_interview_rows(project)
    except ToolkitError:
        rows = []
    if not rows:
        ui.label(f"{len(files)} file{'s' if len(files) != 1 else ''} waiting to be read in: "
                 + ", ".join(p.name for p in files)).classes("text-sm max-w-2xl")
        return

    read_in = {r["interview_id"] for r in rows}
    with ui.column().classes("gap-0 mt-2"):
        for row in rows:
            sessions = f" · {row['sessions']} sessions pooled" if row["sessions"] > 1 else ""
            ui.label(f"{row['narrator']} — {row['words']:,} words, "
                     f"{row['paragraphs']} paragraphs{sessions}").classes("text-sm")
    if len(read_in) < len(files):
        ui.label(f"{len(files) - len(read_in)} of the {len(files)} files have not been read in "
                 f"yet — use 'Read them in'.").classes("text-xs tk-caution")


def _flow(project, refresh) -> None:
    """Read them in, try it, run it. The middle one is where the money starts."""
    if not workspaces.unsynced_files(project):
        return

    title = content.UNSYNCED_IMPORT.title
    with ui.row().classes("gap-2 items-center mt-3"):
        ui.button(title, icon="play_arrow",
                  on_click=lambda: launch(title, list(content.UNSYNCED_IMPORT.argv), HREF)) \
            .props("dense")
        inline_state(title)
        ui.label(content.UNSYNCED_IMPORT.blurb).classes("text-xs opacity-70 max-w-lg")

    if not project.unsynced_paragraphs_path.exists():
        return

    record = _record()
    fresh = _freshness(project)
    demo_title = content.unsynced_job_title(content.DEMO_RUN)
    full_title = content.unsynced_job_title(content.FULL_RUN)

    with ui.card().classes("w-full mt-2"):
        with ui.row().classes("w-full items-start gap-6 flex-wrap"):
            with ui.column().classes("gap-1 grow min-w-64"):
                ui.label("Try it on a couple").classes("text-sm font-medium")
                ui.label("Summarizes a few of them and writes a review page. Nothing is saved "
                         "to the project.").classes("text-xs opacity-70 max-w-md")
                _run_button(demo_title, "Run the demo", demo=True, state=fresh["demo"],
                            props="dense outline", refresh=refresh)
            with ui.column().classes("gap-1 grow min-w-64"):
                ui.label("Summarize all of them").classes("text-sm font-medium")
                ui.label("Asks what it will cost before spending anything. The summaries join "
                         "the collection's own.").classes("text-xs opacity-70 max-w-md")
                _run_button(full_title, "Summarize them all", demo=False, state=fresh["full"],
                            props="dense color=primary", refresh=refresh,
                            blocked=not record.get("demo"))
                if record.get("full"):
                    ui.label(f"{record['full']['n_units']} summarized").classes("text-xs opacity-60")

    _pages(project)
    run_status(titles={demo_title, full_title}, on_finished=refresh, unit="transcripts")


def _run_button(title: str, label: str, *, demo: bool, state: str, props: str, refresh,
                blocked: bool = False) -> None:
    from ...steps import freshness as fresh_mod

    button = ui.button(label, icon="science" if demo else "play_arrow",
                       on_click=lambda: launch(title, content.unsynced_argv(demo=demo), HREF)) \
        .props(props)
    if blocked:
        button.disable()
        button.tooltip("Run the demo first and read it — the toolkit refuses a full run behind "
                       "a demo that has not happened.")
    elif state == fresh_mod.CURRENT:
        button.disable()
        button.tooltip("It has already run on these, and nothing that would change the answer "
                       "has been edited since. Running it again would get the same result back.")
    elif state == fresh_mod.PARTIAL:
        button.tooltip("Some of these are already summarized — running it again does only what "
                       "is new.")


def _pages(project) -> None:
    found = [(review.title, f"/diags/summarize/{review.filename}")
             for review in content.UNSYNCED_REVIEWS
             if (project.diags_dir / "summarize" / review.filename).is_file()]
    if not found:
        return
    with ui.row().classes("gap-3 flex-wrap items-center mt-2"):
        for i, (title, url) in enumerate(found):
            ui.button(title, icon="open_in_new",
                      on_click=lambda _, u=url: ui.navigate.to(u, new_tab=True)) \
                .props("dense" + (" color=primary" if i == 0 else " outline"))


def _record() -> dict:
    try:
        return CONTEXT.status()["steps"].get(content.UNSYNCED_STEP_KEY, {})
    except ToolkitError:
        return {}


def _freshness(project) -> dict:
    from ...steps.freshness import freshness

    try:
        return freshness(project, "summarize", content.UNSYNCED)
    except (ToolkitError, OSError):
        return {"demo": "none", "full": "none"}
