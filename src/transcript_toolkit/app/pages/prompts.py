"""Reading and changing the instructions a step sends, and the house rules attached to them.

A prompt is a plain text file in the project's own `prompts/` folder — one copy per project, so
rewording one here cannot change any other project. This is a view onto that file: the step reads
exactly what is shown, and `core/prompts` is what says which file that is.
"""
from __future__ import annotations

from nicegui import ui

from ...core import prompts as core_prompts
from ...core.prompts import prompt_name, prompt_path
from ...errors import ToolkitError
from ...project import reset_prompt
from ..context import CONTEXT
from .common import guard

INTRO = ("These are the instructions the toolkit sends with every call for this step. Rewording "
         "them changes what comes back.")

STALE_NOTE = ("Saving makes this step's demo out of date, which is what you want: try it out on "
              "the demo interviews again and read the result before running the whole collection.")

# Tall enough to read a whole prompt in, which is the point of showing it at all.
EDITOR_HEIGHT = "36rem"
ADDENDUM_HEIGHT = "18rem"


def text_area(value: str, height: str = EDITOR_HEIGHT):
    """A box for writing something long in. White, so it reads as a field and not as the page."""
    return ui.textarea(value=value) \
        .props(f'outlined input-class=font-mono input-style="height: {height}"') \
        .classes("w-full text-xs")


def prompt_editor(step: str, set_name: str | None = None, on_saved=None,
                  shared_note: str = "") -> None:
    project = CONTEXT.require_project()
    try:
        name = prompt_name(project, step, set_name)
        path = prompt_path(project, step, set_name)
        body = path.read_text()
    except (ToolkitError, OSError) as e:
        guard(ToolkitError(f"Could not read this step's prompt: {e}"))
        return

    ui.label(INTRO).classes("text-sm opacity-80 max-w-2xl")
    if shared_note:
        ui.label(shared_note).classes("text-xs tk-caution max-w-2xl")
    ui.label(f"prompts/{name}").classes("text-xs opacity-60 font-mono")
    editor = text_area(body)
    ui.label(STALE_NOTE).classes("text-xs opacity-60 max-w-2xl")

    def save() -> None:
        try:
            path.write_text(editor.value)
        except OSError as e:
            guard(ToolkitError(f"Could not save {path}: {e}"))
            return
        ui.notify("Prompt saved. Run the demo again to see what it does.", type="positive")
        if on_saved:
            on_saved()

    def restore() -> None:
        with ui.dialog() as dialog, ui.card().classes("max-w-md"):
            ui.label("Put the original prompt back?").classes("text-lg font-medium")
            ui.label(f"Whatever is in prompts/{name} now is replaced by the one the toolkit "
                     f"ships with. Copy anything you want to keep out of the box above first.") \
                .classes("text-sm")

            def go() -> None:
                try:
                    reset_prompt(project, name)
                except ToolkitError as e:
                    guard(e)
                    return
                dialog.close()
                ui.notify("The original prompt is back.", type="positive")
                if on_saved:
                    on_saved()

            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Cancel", on_click=dialog.close).props("flat dense")
                ui.button("Put it back", on_click=go).props("dense color=negative")
        dialog.open()

    with ui.row().classes("gap-2"):
        ui.button("Save the prompt", icon="save", on_click=save).props("dense")
        ui.button("Put the original back", icon="restore", on_click=restore).props("dense flat")


# --- house rules (an addendum file) ----------------------------------------------------------

NEW_ADDENDUM_HELP = (
    "House rules are added to the end of this step's prompt, so they apply to every call without "
    "your having to touch the prompt itself. Write the things your project decides rather than "
    "the model: how a name is spelled, what to call something, what never to abbreviate."
)


def addendum_dialog(title: str, name: str, body: str, on_write) -> None:
    """Write or rewrite a set of house rules. `on_write(name, text)` does the saving."""
    with ui.dialog().props("full-width") as dialog, ui.card().classes("w-full"):
        ui.label(title).classes("text-lg font-medium")
        ui.label(NEW_ADDENDUM_HELP).classes("text-xs opacity-70 max-w-2xl")
        name_field = ui.input("What to call them", value=name,
                              placeholder="house style").props("dense outlined").classes("w-full")
        name_field.set_visibility(not name)
        editor = text_area(body, ADDENDUM_HEIGHT)

        def save() -> None:
            try:
                on_write(name or name_field.value, editor.value)
            except ToolkitError as e:
                guard(e)
                return
            dialog.close()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat dense")
            ui.button("Save", icon="save", on_click=save).props("dense")
    dialog.open()


def new_addendum(on_saved) -> None:
    """Write a new set of house rules and hand back its workspace-relative path."""
    project = CONTEXT.require_project()

    def write(title: str, text: str) -> None:
        if not text.strip():
            raise ToolkitError("Write the rules first, or press Cancel.")
        path = core_prompts.write_addendum(project, title, text)
        ui.notify(f"Saved {path}.", type="positive")
        on_saved(path)

    addendum_dialog("New house rules", "", "", write)


def edit_addendum(rel_path: str, on_saved) -> None:
    """Change a set of house rules that is already attached."""
    project = CONTEXT.require_project()
    path = project.root / rel_path
    if not path.is_file():
        guard(ToolkitError(f"{rel_path} is not in this project any more. Choose another, or "
                           f"write a new one."))
        return

    def write(_title: str, text: str) -> None:
        path.write_text(text.strip() + "\n")
        ui.notify("Saved. Run the demo again to see what it does.", type="positive")
        on_saved(rel_path)

    addendum_dialog(f"House rules — {path.name}", path.name, path.read_text(), write)
