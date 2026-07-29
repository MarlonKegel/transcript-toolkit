"""Workspace page: pick or make a project, give it a key and transcripts, import them.

This is the whole of what used to be a terminal session — `toolkit init`, editing a hidden
.env in TextEdit, copying files into data/, `toolkit import` — in one page, in that order.
"""
from __future__ import annotations

from nicegui import ui

from ...errors import ToolkitError
from .. import content, workspaces
from ..context import CONTEXT
from .browse import browse_button
from .common import guard, launch, run_panel, section, shell, shown_name
from .sample import sample_section

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
            _demo_sample(body.refresh)

        body()
        run_panel(on_finished=body.refresh)


def _rename(project) -> None:
    """Projects made before the toolkit derived the name are all called the same thing. This
    is the one-field fix, so nobody has to be told to edit config.yaml."""
    with ui.expansion("Rename it", icon="edit").classes("w-full"):
        ui.label("Changes what this project is called. Its folder keeps the name it has — "
                 "rename that in Finder if you want to.").classes("text-xs opacity-70")
        with ui.row().classes("w-full items-end gap-2"):
            field = ui.input("Project name", value=shown_name(project)).classes("grow")

            def save() -> None:
                try:
                    workspaces.rename_project(project, field.value)
                except ToolkitError as e:
                    guard(e)
                    return
                ui.navigate.to(HREF)

            ui.button("Save", on_click=save).props("dense")


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
            # The project's name, not its folder — the folder is on the line below, where a
            # path belongs.
            ui.label(shown_name(project)).classes("text-xl font-medium")
            ui.label(str(project.root)).classes("text-xs opacity-60")
            _rename(project)
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
        ui.label("Open a project already on this Mac").classes("text-xs uppercase opacity-60")
        with ui.row().classes("w-full items-end gap-2 flex-wrap"):
            path = ui.input("Project folder",
                            placeholder=str(workspaces.suggested_parent() / "my-archive")) \
                .classes("grow min-w-64")
            browse_button(path, title="Find your project folder",
                          hint="Project folders are marked. Open the one you want and use it.")
            ui.button("Open", icon="folder_open",
                      on_click=lambda: _reopen(path.value)).props("dense")

    with ui.card().classes("w-full"):
        ui.label("Start a new project").classes("text-xs uppercase opacity-60")
        name = ui.input("Project name", value="My Oral History Project").classes("w-full")
        with ui.row().classes("w-full items-end gap-2 flex-wrap"):
            parent = ui.input("Inside this folder", value=str(workspaces.suggested_parent())) \
                .classes("grow min-w-64")
            browse_button(parent, title="Where should the project folder go?",
                          hint="A new folder is made inside the one you choose.")
        where = ui.label().classes("text-xs opacity-60 break-all")

        def preview() -> None:
            """Show the folder the name will produce, so it is never a surprise later."""
            try:
                where.set_text(f"Its folder will be: {workspaces.planned_folder(parent.value, name.value)}")
            except ToolkitError as e:
                where.set_text(str(e))

        name.on_value_change(preview)
        parent.on_value_change(preview)
        preview()

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
    section("Transcripts", "Word files of SYNC'd (timestamped) transcripts — one per interview, "
                           "or one per session.")
    with ui.card().classes("w-full"):

        @ui.refreshable
        def listing() -> None:
            """What is in the folder, and whether import has read it yet."""
            rows = workspaces.transcript_rows(project)
            if not rows:
                ui.label("No transcripts yet — drop them in below.").classes("text-sm")
                return
            waiting = [r for r in rows if not r["imported"]]
            ui.label(f"{len(rows)} transcript{'s' if len(rows) != 1 else ''} in this project"
                     + (f", {len(waiting)} not imported yet" if waiting else ", all imported")) \
                .classes("text-sm font-medium")
            with ui.column().classes("w-full gap-0 max-h-72 overflow-auto"):
                for row in rows:
                    done = row["imported"]
                    with ui.row().classes("items-center gap-2 w-full py-0.5"):
                        ui.icon("check_circle" if done else "schedule") \
                            .classes("text-green-600" if done else "text-amber-600") \
                            .props("size=1rem")
                        ui.label(row["filename"]).classes(
                            "text-xs font-mono " + ("" if done else "font-medium"))
                        ui.space()
                        ui.label("imported" if done else "not imported yet") \
                            .classes("text-xs " + ("opacity-60" if done
                                                   else "text-amber-700 dark:text-amber-400"))

        listing()

        # The upload box is built once and never rebuilt by an upload: refreshing the part of
        # the page that holds it while files are still arriving is what used to drop most of a
        # multi-file drop on the floor. Only the list above is redrawn.
        async def receive(e) -> None:
            added, refused = [], []
            for upload in e.files:
                try:
                    workspaces.add_transcript(project, upload.name, await upload.read())
                    added.append(upload.name)
                except ToolkitError as err:
                    refused.append(str(err))
            listing.refresh()
            if added:
                ui.notify(f"Added {len(added)} transcript{'s' if len(added) != 1 else ''}."
                          + (" Click Import to read them in." if added else ""),
                          type="positive")
            for message in refused:
                guard(ToolkitError(message))

        ui.upload(on_multi_upload=receive, multiple=True, auto_upload=True,
                  label="Drop .docx files here").props("accept=.docx flat bordered") \
            .classes("w-full")
        ui.label(f"They are copied into {project.data_dir}").classes("text-xs opacity-60")

        with ui.row().classes("gap-2 items-center mt-2"):
            ui.button("Import", icon="play_arrow", on_click=_import_click).props("dense")
            ui.label("Reads the .docx files into the dataset every step works from. "
                     "Run it again whenever you add or change a transcript.") \
                .classes("text-xs opacity-70 max-w-lg")


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


def _demo_sample(refresh) -> None:
    """The demo interviews live here, with the project — every step's demo uses them."""
    if not CONTEXT.require_project().paragraphs_path.exists():
        return
    section("Demo interviews", "Trying a step out runs it on these interviews only. The same "
                               "few are used by every step, so what you read is comparable.")
    sample_section(HREF, refresh)


def register() -> None:
    ui.page(HREF, title="Workspace — Transcript Toolkit")(workspace_page)
