"""Export page: turn everything the pipeline produced into one spreadsheet."""
from __future__ import annotations

from nicegui import ui

from ...core.console import reveal
from ...errors import ToolkitError
from ..context import CONTEXT
from .common import guard, launch, run_panel, section, shell

HREF = "/export"


def export_page() -> None:
    from ...steps.export import DEFAULT_LOCATION_MODE, LOCATION_MODES

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

        with ui.card().classes("w-full"):
            included = status["deliverables"]
            if included:
                ui.label("Will include: " + ", ".join(included)).classes("text-sm")
            else:
                ui.label("Nothing has been produced yet — run a step first.") \
                    .classes("text-sm opacity-70")

            configured = configured_location_mode(project) or DEFAULT_LOCATION_MODE
            ui.label("How places should appear").classes("text-sm font-medium mt-2")
            mode = ui.radio({k: f"{k.replace('_', ' ')} — {v}" for k, v in LOCATION_MODES.items()},
                            value=configured).props("dense")
            ui.label("This is the config.yaml setting; changing it here applies to this export "
                     "only.").classes("text-xs opacity-60")

            ui.button("Build the spreadsheet", icon="table_view",
                      on_click=lambda: launch("Export", ["export", "--locations", mode.value],
                                              HREF)) \
                .props("dense color=primary").classes("mt-2")

        out = project.outputs_dir / "export.xlsx"
        if out.exists():
            with ui.card().classes("w-full"):
                ui.label("Last export").classes("text-sm font-medium")
                ui.label(str(out)).classes("text-xs opacity-70")
                ui.button("Show it in Finder", icon="folder_open",
                          on_click=lambda: reveal(out.parent)).props("dense flat")

        run_panel(page_href=HREF)


def configured_location_mode(project) -> str | None:
    """The workspace's configured export.locations, if it set one."""
    from ...core.config import load_root_config
    return (load_root_config(project).get("export") or {}).get("locations")


def register() -> None:
    ui.page(HREF, title="Export — Transcript Toolkit")(export_page)
