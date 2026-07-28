"""Workspace page: pick or make a project, give it a key and transcripts, import them.

This is the whole of what used to be a terminal session — `toolkit init`, editing a hidden
.env in TextEdit, copying files into data/, `toolkit import` — in one page, in that order.
"""
from __future__ import annotations

from nicegui import ui

from ...errors import ToolkitError
from .. import content, workspaces
from ..context import CONTEXT
from .common import guard, launch, run_panel, section, shell

HREF = "/workspace"


def workspace_page() -> None:
    with shell(HREF, needs_workspace=False):
        _open_or_create()
        if CONTEXT.project is None:
            return
        _api_key()

        @ui.refreshable
        def body() -> None:
            _transcripts(body.refresh)
            _import_results()

        body()
        run_panel(on_finished=body.refresh)


def _reopen(path: str) -> None:
    try:
        CONTEXT.open(workspaces.open_workspace(path))
    except ToolkitError as e:
        guard(e)
        return
    ui.navigate.to(HREF)


def _open_or_create() -> None:
    project = CONTEXT.project
    if project is not None:
        with ui.card().classes("w-full"):
            ui.label("Open project").classes("text-xs uppercase opacity-60")
            ui.label(project.root.name).classes("text-xl font-medium")
            ui.label(str(project.root)).classes("text-xs opacity-60")
        with ui.expansion("Open a different project", icon="folder").classes("w-full"):
            _picker()
        return

    section("Open a project", "A project is one folder holding a set of transcripts and "
                              "everything the toolkit makes from them.")
    _picker()


def _picker() -> None:
    recents = []
    try:
        recents = workspaces.load_registry()
    except ToolkitError as e:
        guard(e)

    if recents:
        with ui.card().classes("w-full"):
            ui.label("Recent").classes("text-xs uppercase opacity-60")
            for entry in recents:
                with ui.row().classes("items-center w-full gap-2"):
                    with ui.column().classes("gap-0 grow"):
                        ui.label(entry.get("name") or entry["path"]).classes("text-sm font-medium")
                        ui.label(entry["path"]).classes("text-xs opacity-60")
                    ui.button("Open", on_click=lambda _, p=entry["path"]: _reopen(p)) \
                        .props("dense flat")
                    ui.button(icon="close", on_click=lambda _, p=entry["path"]: _forget(p)) \
                        .props("dense flat round").tooltip("Remove from this list "
                                                           "(the folder is left alone)")

    with ui.card().classes("w-full"):
        ui.label("Open by folder").classes("text-xs uppercase opacity-60")
        path = ui.input("Path to the project folder",
                        placeholder=str(workspaces.suggested_parent() / "my-archive")) \
            .classes("w-full")
        ui.button("Open", icon="folder_open", on_click=lambda: _reopen(path.value)).props("dense")

    with ui.card().classes("w-full"):
        ui.label("Start a new project").classes("text-xs uppercase opacity-60")
        parent = ui.input("Inside this folder", value=str(workspaces.suggested_parent())) \
            .classes("w-full")
        name = ui.input("Project name", placeholder="my-archive").classes("w-full")

        def create() -> None:
            try:
                CONTEXT.open(workspaces.create_workspace(parent.value, name.value))
            except ToolkitError as e:
                guard(e)
                return
            ui.navigate.to(HREF)

        ui.button("Create", icon="add", on_click=create).props("dense")


def _forget(path: str) -> None:
    workspaces.forget(path)
    ui.navigate.to(HREF)


def _api_key() -> None:
    project = CONTEXT.require_project()
    section("OpenAI key")
    with ui.card().classes("w-full"):
        if workspaces.has_api_key(project):
            with ui.row().classes("items-center gap-2"):
                ui.icon("check_circle").classes("text-green-600")
                ui.label("A key is saved in this project.").classes("text-sm")
            ui.label("Runs are billed to whoever owns it. Replace it below if it changes.") \
                .classes("text-xs opacity-70")
        else:
            ui.label("No key yet — nothing can run without one. Ask whoever administers your "
                     "team's OpenAI account for one.").classes("text-sm")
        field = ui.input("Paste a key", password=True, placeholder="sk-...").classes("w-full")

        def save() -> None:
            try:
                workspaces.set_api_key(project, field.value)
            except ToolkitError as e:
                guard(e)
                return
            ui.navigate.to(HREF)

        ui.button("Save key", icon="key", on_click=save).props("dense")
        ui.label("It is stored in this project's .env file and never leaves your Mac except "
                 "in calls to OpenAI.").classes("text-xs opacity-60")


def _transcripts(refresh) -> None:
    project = CONTEXT.require_project()
    n = workspaces.transcript_count(project)
    section("Transcripts", "Word files of SYNC'd (timestamped) transcripts — one per interview, "
                           "or one per session.")
    with ui.card().classes("w-full"):
        ui.label(f"{n} .docx in this project" if n else "No transcripts yet.").classes("text-sm")

        async def receive(e) -> None:
            try:
                workspaces.add_transcript(project, e.file.name, await e.file.read())
            except ToolkitError as err:
                guard(err)
                return
            ui.notify(f"Added {e.file.name}", type="positive")
            refresh()

        ui.upload(on_upload=receive, multiple=True, auto_upload=True,
                  label="Drop .docx files here").props("accept=.docx flat bordered") \
            .classes("w-full")
        ui.label(f"They are copied into {project.data_dir}").classes("text-xs opacity-60")

        with ui.row().classes("gap-2 items-center mt-2"):
            ui.button("Import", icon="play_arrow",
                      on_click=lambda: launch("Import", list(content.IMPORT.argv), HREF)) \
                .props("dense")
            ui.label("Reads the .docx files into the dataset every step works from. "
                     "Run it again whenever you add or change a transcript.") \
                .classes("text-xs opacity-70 max-w-lg")


def _import_results() -> None:
    from ...steps.import_ import dataset_summary

    project = CONTEXT.require_project()
    if not project.paragraphs_path.exists():
        return
    try:
        summary = dataset_summary(project)
    except ToolkitError as e:
        guard(e)
        return

    section("What was imported", "Check the speaker roles: if an interviewer shows up as "
                                 "narrator, fix interviewer_labels in config.yaml and import again.")
    with ui.card().classes("w-full"):
        ui.label(f"{summary['n_transcripts']} transcripts · {summary['n_paragraphs']:,} "
                 f"paragraphs · {summary['n_narrators']} narrators").classes("text-sm font-medium")

        ui.table(columns=[{"name": "speaker_role", "label": "Role", "field": "speaker_role",
                           "align": "left"},
                          {"name": "speaker_label", "label": "As written in the transcript",
                           "field": "speaker_label", "align": "left"},
                          {"name": "n", "label": "Paragraphs", "field": "n", "align": "right"}],
                 rows=summary["roles"], row_key="speaker_label").props("dense flat").classes("w-full")

        if summary["flagged"]:
            with ui.card().classes("w-full bg-amber-50 dark:bg-amber-900/30"):
                ui.label(f"{len(summary['flagged'])} of {len(summary['regimes'])} transcripts "
                         f"are timestamped only on speaker turns, not on every paragraph.") \
                    .classes("text-sm")
                ui.label("The pipeline still runs; clip start and end times are just coarser "
                         "for those.").classes("text-xs opacity-70")
                for row in summary["flagged"]:
                    ui.label(f"{row['interview_id']} — {row['detail']}").classes("text-xs")
        else:
            ui.label("Every paragraph carries its own timestamp.").classes("text-xs opacity-70")

        if summary["multi_session"]:
            ui.label("Multi-session narrators (their sessions are pooled for summaries and "
                     "interview tags):").classes("text-sm mt-2")
            for narrator, sessions in summary["multi_session"].items():
                ui.label(f"{narrator} ← {', '.join(sessions)}").classes("text-xs opacity-80")


def register() -> None:
    ui.page(HREF, title="Workspace — Transcript Toolkit")(workspace_page)
