"""Reading and changing the instructions a step sends.

A prompt is a plain text file in the project's own `prompts/` folder — one copy per project, so
rewording one here cannot change any other project. This is a view onto that file: the step
reads exactly what is shown, and `core/prompts` is what says which file that is.
"""
from __future__ import annotations

from nicegui import ui

from ...core.prompts import prompt_name, prompt_path
from ...errors import ToolkitError
from ...project import reset_prompt
from ..context import CONTEXT
from .common import guard

INTRO = ("These are the instructions the toolkit sends with every call for this step. Rewording "
         "them is the main way to change what comes back — more than any setting.")

STALE_NOTE = ("Saving makes this step's demo out of date, which is what you want: try it out on "
              "the demo interviews again and read the result before running the whole collection.")


def prompt_editor(step: str, set_name: str | None = None, on_saved=None) -> None:
    project = CONTEXT.require_project()
    try:
        name = prompt_name(project, step, set_name)
        path = prompt_path(project, step, set_name)
        body = path.read_text()
    except (ToolkitError, OSError) as e:
        guard(ToolkitError(f"Could not read this step's prompt: {e}"))
        return

    ui.label(INTRO).classes("text-sm opacity-80 max-w-2xl")
    ui.label(f"prompts/{name}").classes("text-xs opacity-60 font-mono")
    editor = ui.textarea(value=body).props("outlined input-class=font-mono") \
        .classes("w-full text-xs")
    editor.style("min-height: 22rem")
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
