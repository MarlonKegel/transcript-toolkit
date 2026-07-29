"""Export page: turn everything the pipeline produced into one spreadsheet."""
from __future__ import annotations

from nicegui import ui

from ...core.console import reveal
from ...errors import ToolkitError
from ..context import CONTEXT
from .common import guard, launch, run_status, section, shell, terminal_viewer
from .settings_form import settings_form

HREF = "/export"


def export_page() -> None:
    with shell(HREF):
        if CONTEXT.project is None:
            return
        project = CONTEXT.require_project()
        try:
            status = CONTEXT.status()
        except ToolkitError as e:
            guard(e)
            return

        section("Export", "One Excel file with everything that has been produced so far. "
                          "Steps that haven't run are simply left out, so exporting early is "
                          "fine — run it again later and it will have more in it.")

        def refresh_all() -> None:
            build.refresh()
            rest.refresh()

        @ui.refreshable
        def build() -> None:
            with ui.card().classes("w-full"):
                included = status["deliverables"]
                if included:
                    ui.label("Will include: " + ", ".join(included)).classes("text-sm")
                else:
                    ui.label("Nothing has been produced yet — run a step first.") \
                        .classes("text-sm opacity-70")
                ui.button("Build the spreadsheet", icon="table_view",
                          on_click=lambda: launch("Export", ["export"], HREF)) \
                    .props("dense color=primary").classes("mt-2")

        @ui.refreshable
        def rest() -> None:
            _result(project)
            section("Change how this step works")
            with ui.expansion("Settings for this step", icon="tune").classes("w-full"):
                settings_form("export", on_saved=refresh_all, note=False)

        build()
        run_status(on_finished=refresh_all)      # under the button that starts it
        rest()
        terminal_viewer()


def _result(project) -> None:
    out = export_path(project)
    if not out.exists():
        return
    with ui.card().classes("w-full"):
        ui.label("Last export").classes("text-sm font-medium")
        ui.label(str(out)).classes("text-xs opacity-70")
        ui.button("Show it in Finder", icon="folder_open",
                  on_click=lambda: reveal(out.parent)).props("dense flat")


def export_path(project):
    """Where the spreadsheet lands — the workspace can rename it, so ask its config."""
    from ...core.config import load_step_config
    from ...steps.export import DEFAULT_FILENAME
    name = load_step_config(project, "export").get("filename") or DEFAULT_FILENAME
    return project.outputs_dir / name


def register() -> None:
    ui.page(HREF, title="Export — Transcript Toolkit")(export_page)
