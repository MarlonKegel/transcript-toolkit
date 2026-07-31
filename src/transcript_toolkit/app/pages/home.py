"""Home: every project on this Mac, where each one has got to, and how to start another.

This is the landing page — what the app opens on, and where the icon in the corner brings you
back to. One project is one folder; opening one takes you to its workspace page.
"""
from __future__ import annotations

from nicegui import ui

from ...errors import ToolkitError
from .. import stage, theme, workspaces
from ..context import CONTEXT
from .browse import browse_button
from .common import guard, section, shell

HREF = "/"


def home() -> None:
    with shell(HREF, needs_workspace=False):
        _missing_notice()

        @ui.refreshable
        def body() -> None:
            _projects(body.refresh)
            _open_existing()
            _create_new()

        body()


def _missing_notice() -> None:
    """A project that was open and whose folder has since gone. The workspace page asks what
    happened; here it is enough to say which one is affected."""
    if CONTEXT.missing is None:
        return
    with ui.card().classes(f"w-full {theme.WARN}"):
        ui.label("One of your projects is not where it was").classes("text-lg font-medium")
        ui.label(str(CONTEXT.missing)).classes("text-xs font-mono opacity-70 break-all")
        ui.link("Sort it out on the workspace page", "/workspace").classes("text-sm")


def _projects(refresh) -> None:
    try:
        entries = stage.all_projects()
    except ToolkitError as e:
        guard(e)
        return

    section("Your projects", "A project is one folder holding a set of transcripts and everything "
                             "the toolkit makes from them.")
    if not entries:
        with ui.card().classes("w-full"):
            ui.label("No projects yet.").classes("text-sm font-medium")
            ui.label("Start one below. Everything after that happens inside its folder.") \
                .classes("text-sm opacity-70")
        return

    open_now = str(CONTEXT.project.root) if CONTEXT.project is not None else None
    for entry in entries:
        with ui.card().classes("w-full py-3"):
            if not entry["found"]:
                _lost(entry, refresh)
                continue
            _project_row(entry, is_open=entry["path"] == open_now)


def _project_row(entry: dict, *, is_open: bool) -> None:
    with ui.row().classes("items-center w-full gap-3 flex-wrap"):
        with ui.column().classes("gap-0 grow min-w-64"):
            with ui.row().classes("items-center gap-2"):
                ui.label(entry["name"]).classes("text-base font-medium")
                if is_open:
                    ui.chip("open", color="primary", text_color="white") \
                        .props("dense square").classes("text-xs")
            ui.label(entry["path"]).classes("text-xs opacity-60 break-all")
        with ui.column().classes("gap-0 items-end"):
            ui.label(f"{entry['transcripts']} transcript"
                     f"{'s' if entry['transcripts'] != 1 else ''}"
                     + ("" if entry["imported"] else " · not imported yet")) \
                .classes("text-xs opacity-70")
            ui.label(f"{entry['steps_done']} of {entry['steps_total']} steps run on everything") \
                .classes("text-xs opacity-70")
        ui.button("Open" if not is_open else "Go to it", icon="folder_open",
                  on_click=lambda _, p=entry["path"]: _open(p)).props("dense")

    with ui.row().classes("items-center gap-2 w-full"):
        ui.icon("arrow_forward", size="1rem").classes("opacity-50")
        ui.label(f"Next: {entry['next']}").classes("text-sm")
        ui.label(entry["why"]).classes("text-xs opacity-60 truncate")


def _lost(entry: dict, refresh) -> None:
    with ui.row().classes("items-center w-full gap-3 flex-wrap"):
        with ui.column().classes("gap-0 grow min-w-64"):
            ui.label("Not found").classes("text-base font-medium tk-caution")
            ui.label(entry["path"]).classes("text-xs opacity-60 break-all")
        ui.button("Remove from this list", icon="close",
                  on_click=lambda _, p=entry["path"]: _forget(p, refresh)) \
            .props("dense flat").tooltip("The folder itself is left alone")
    ui.label(entry["trouble"]).classes("text-xs opacity-60 whitespace-pre-line")


def _forget(path: str, refresh) -> None:
    workspaces.forget(path)
    refresh()


def _open(path: str) -> None:
    try:
        CONTEXT.open(workspaces.open_workspace(path))
    except ToolkitError as e:
        guard(e)
        return
    ui.navigate.to("/workspace")


def _open_existing() -> None:
    with ui.expansion("Open a project that is not in the list", icon="folder").classes("w-full"):
        ui.label("A project made on another Mac, or one this app has not seen before.") \
            .classes("text-xs opacity-70")
        with ui.row().classes("w-full items-end gap-2 flex-wrap"):
            path = ui.input("Project folder",
                            placeholder=str(workspaces.suggested_parent() / "my-archive")) \
                .classes("grow min-w-64")
            browse_button(path, title="Find your project folder",
                          hint="Project folders are marked. Open the one you want and use it.")
            ui.button("Open", icon="folder_open",
                      on_click=lambda: _open(path.value)).props("dense")


def _create_new() -> None:
    section("Start a new project")
    with ui.card().classes("w-full"):
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
                where.set_text(f"Its folder will be: "
                               f"{workspaces.planned_folder(parent.value, name.value)}")
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
            ui.navigate.to("/workspace")

        ui.button("Create", icon="add", on_click=create).props("dense")


def register() -> None:
    ui.page(HREF, title="Transcript Toolkit")(home)
