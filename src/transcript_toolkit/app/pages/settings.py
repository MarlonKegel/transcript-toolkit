"""Settings: the installation, the desktop app, this project's config file, and quitting."""
from __future__ import annotations

import sys

from nicegui import app, run, ui

from ... import __version__
from ...core.console import reveal
from ...errors import ToolkitError
from .. import DEFAULT_PORT
from ..context import CONTEXT
from .common import guard, launch_global, run_panel, section, shell

HREF = "/settings"


def settings_page() -> None:
    with shell(HREF, needs_workspace=False):
        _version()
        _desktop_app()
        _config()
        _quit()
        run_panel()


def _version() -> None:
    section("Version")
    with ui.card().classes("w-full"):
        ui.label(f"transcript-toolkit {__version__}").classes("text-sm font-medium")
        notice = ui.label("checking for a newer version…").classes("text-xs opacity-60")

        async def check() -> None:
            from ...core.update import update_notice
            # A network call, so off the main thread: a slow or unreachable GitHub must never
            # make the page hang.
            message = await run.io_bound(update_notice)
            notice.text = message.strip() if message else "This is the latest version."
            notice.classes(replace="text-xs opacity-80 whitespace-pre-line")

        ui.timer(0.1, check, once=True)

        with ui.row().classes("gap-2 items-center"):
            ui.button("Install the latest version", icon="system_update",
                      on_click=lambda: launch_global("Update", ["update"], HREF)).props("dense flat")
        ui.label("After updating, quit the app below and open it again — the running app keeps "
                 "using the old version until you do.").classes("text-xs opacity-60")


def _desktop_app() -> None:
    if sys.platform != "darwin":
        return
    from ..launcher import app_path, log_path

    section("Desktop app", "A double-clickable app in your Applications folder that starts "
                           "this window.")
    with ui.card().classes("w-full"):
        exists = app_path().exists()
        ui.label(f"{app_path()}" + ("" if exists else "  (not created yet)")) \
            .classes("text-sm" if exists else "text-sm opacity-70")

        def install() -> None:
            from ..launcher import install_launcher
            try:
                path = install_launcher(port=None if CONTEXT.port == DEFAULT_PORT else CONTEXT.port)
            except ToolkitError as e:
                guard(e)
                return
            ui.notify(f"Created {path.name} — find it in Applications and drag it to your Dock.",
                      type="positive", multi_line=True, close_button="OK")

        ui.button("Create it again" if exists else "Create the app", icon="apps",
                  on_click=install).props("dense")
        ui.label(f"Startup messages go to {log_path()}").classes("text-xs opacity-60")
        if exists:
            ui.label("Re-creating it may make macOS ask once more for access to your Documents "
                     "folder. That is expected.").classes("text-xs opacity-60")


def _config() -> None:
    project = CONTEXT.project
    if project is None:
        return
    import yaml

    section("Settings file", "config.yaml holds this project's settings — which model each step "
                             "uses, how interviewer labels are spelled, and so on. The comments "
                             "in it explain each one.")
    with ui.card().classes("w-full"):
        ui.label(str(project.config_path)).classes("text-xs opacity-60")
        editor = ui.textarea(value=project.config_path.read_text()) \
            .props("outlined autogrow input-class=font-mono").classes("w-full text-xs")

        def save() -> None:
            try:
                yaml.safe_load(editor.value)
            except yaml.YAMLError as e:
                guard(ToolkitError(f"That is not valid YAML, so it was not saved:\n{e}"))
                return
            project.config_path.write_text(editor.value)
            ui.notify("Saved. Changing a model or a prompt makes the demos stale — the next "
                      "full run will ask you to redo the demo first.",
                      type="positive", multi_line=True, close_button="OK")

        with ui.row().classes("gap-2"):
            ui.button("Save", icon="save", on_click=save).props("dense")
            ui.button("Show in Finder", icon="folder_open",
                      on_click=lambda: reveal(project.root)).props("dense flat")


def _quit() -> None:
    section("Quit")
    with ui.card().classes("w-full"):
        ui.label("The toolkit keeps running in the background after you close this tab — that is "
                 "how a long run survives a closed window. Quit it when you are done, or after "
                 "installing an update.").classes("text-sm")

        def stop_server() -> None:
            if CONTEXT.jobs.busy:
                guard(ToolkitError(
                    f"'{CONTEXT.jobs.current.title}' is still running. Stop it first — finished "
                    f"calls are saved either way."))
                return
            ui.notify("Stopping. You can close this tab.", type="warning")
            ui.timer(0.5, app.shutdown, once=True)      # let the message reach the browser

        ui.button("Quit the toolkit", icon="power_settings_new", on_click=stop_server) \
            .props("dense color=negative")


def register() -> None:
    ui.page(HREF, title="Settings — Transcript Toolkit")(settings_page)
