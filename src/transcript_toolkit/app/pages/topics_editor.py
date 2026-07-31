"""Editing a topic list in the app.

The alternative to this is telling a curator to open a CSV in Excel, keep the column names
exactly right, and save it back into a folder they have to find first. This is the same file,
edited in place.

Deliberately a *file* editor, not a new concept: what is typed here is written to the
spreadsheet the run reads, checked against the run's own rules, and nothing else about topic
sets changes. What is typed before the list has a name goes to the shipped example file, which
no step will ever tag against.
"""
from __future__ import annotations

from pathlib import Path

from nicegui import ui

from ...errors import ToolkitError
from .. import theme, topic_lists
from ..context import CONTEXT
from .common import guard, info

AUTOSAVE_S = 20.0

NAME_EXAMPLES = "collection, filter, themes"

EDITOR_EXPLAINER = (
    "A topic list is one row per topic. The name is what you will see on the exported "
    "spreadsheet; the description is the only thing the model reads when it decides whether a "
    "clip belongs to that topic.\n\n"
    "Write descriptions that say what counts AND what does not — 'Tag when the clip "
    "substantively discusses education, not on a passing mention' does far more work than "
    "'about education'.\n\n"
    "The id is optional: leave it blank and it is made from the name."
)


def editor(set_name: str | None, path: Path, on_saved) -> None:
    """The table. `set_name` is None while the list is still unnamed (saving asks for one)."""
    project = CONTEXT.require_project()
    rows, guidance = topic_lists.load_rows(path)
    if not rows:
        rows = [{"id": "", "name": "", "description": ""}]
    state = {"rows": rows, "saved": True}

    with ui.row().classes("items-center gap-2 w-full"):
        ui.label("Topics").classes("text-sm font-medium")
        info(EDITOR_EXPLAINER)
        ui.space()
        saved_at = ui.label().classes("text-xs opacity-60")
    if guidance:
        with ui.card().classes(f"w-full {theme.NOTE} py-2"):
            ui.label(guidance).classes("text-xs opacity-80")

    @ui.refreshable
    def table() -> None:
        # The column names are the file's and are not editable: the run looks them up by name.
        with ui.row().classes("w-full gap-2 items-center text-xs uppercase opacity-60"):
            ui.label("id").classes("w-32")
            ui.label("name").classes("w-56")
            ui.label("description").classes("grow")
            ui.label("").classes("w-8")
        for index, row in enumerate(state["rows"]):
            with ui.row().classes("w-full gap-2 items-start"):
                _cell(row, "id", index).classes("w-32").props("placeholder='from the name'")
                _cell(row, "name", index).classes("w-56")
                _cell(row, "description", index, area=True).classes("grow")
                ui.button(icon="delete", on_click=lambda _, i=index: drop(i)) \
                    .props("flat dense round size=sm").classes("mt-2") \
                    .tooltip("Remove this topic")

    def _cell(row: dict, key: str, index: int, area: bool = False):
        element = (ui.textarea(value=row.get(key, "")) if area
                   else ui.input(value=row.get(key, "")))

        def changed(event) -> None:
            state["rows"][index][key] = event.value
            state["saved"] = False
            saved_at.set_text("unsaved changes")

        element.on_value_change(changed)
        return element.props("dense outlined" + (" autogrow" if area else ""))

    def drop(index: int) -> None:
        state["rows"].pop(index)
        if not state["rows"]:
            state["rows"].append({"id": "", "name": "", "description": ""})
        state["saved"] = False
        table.refresh()

    def add() -> None:
        state["rows"].append({"id": "", "name": "", "description": ""})
        state["saved"] = False
        table.refresh()

    table()
    with ui.row().classes("items-center gap-2 mt-2"):
        ui.button("Add a topic", icon="add", on_click=add).props("dense outline")
        ui.space()
        ui.button("Save", icon="save", on_click=lambda: save()).props("dense")

    def save() -> None:
        if set_name is None:
            _ask_for_a_name(project, state["rows"], on_saved)
            return
        try:
            topic_lists.save_existing(project, set_name, path, state["rows"])
        except ToolkitError as e:
            guard(e)
            return
        state["saved"] = True
        saved_at.set_text("saved")
        ui.notify(f"Saved {path.name}.", type="positive")
        on_saved(set_name)

    def autosave() -> None:
        """Keep what has been typed, without validating it — a half-written topic must not
        cost someone their afternoon's work, and must not become a runnable set either."""
        if state["saved"]:
            return
        target = path if set_name else topic_lists.draft_path(project)
        topic_lists.write_rows(target, state["rows"])
        state["saved"] = True
        saved_at.set_text("draft saved" if set_name is None else "saved")

    ui.timer(AUTOSAVE_S, autosave)
    if set_name is None:
        ui.label("Not saved as a topic list yet — click Save to name it. Until then your typing "
                 "is kept in the workspace but no step can use it.") \
            .classes("text-xs opacity-60")


def _ask_for_a_name(project, rows, on_saved) -> None:
    with ui.dialog() as dialog, ui.card().classes("max-w-md"):
        ui.label("Name this topic list").classes("text-lg font-medium")
        ui.label("The name is how you will pick this list when you run the Topics step, and it "
                 "labels its columns in the export. A project can have more than one.") \
            .classes("text-sm")
        field = ui.input("Name", value="main").classes("w-full")
        ui.label(f"For example: {NAME_EXAMPLES}").classes("text-xs opacity-60")

        def confirm() -> None:
            try:
                set_name, path = topic_lists.save_as(project, field.value, rows)
            except ToolkitError as e:
                guard(e)
                return
            dialog.close()
            ui.notify(f"Saved as {path.name}. You can now run Topics on '{set_name}'.",
                      type="positive")
            on_saved(set_name)

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat dense")
            ui.button("Save", on_click=confirm).props("dense")
    dialog.open()
