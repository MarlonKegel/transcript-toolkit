"""Settings: the project as a whole, the installation, and quitting.

Drawn into the drawer behind the gear (see common.shell), so it is one click away from wherever
somebody is rather than a place they have to navigate to and come back from. The `/settings` URL
still works and opens the same drawer.

Only what belongs to the whole project or to the app is here. A setting that belongs to one step
is on that step's page, next to the button that uses it.
"""
from __future__ import annotations

import sys

from nicegui import app, run, ui

from ... import __version__
from ...core import settings as config_settings
from ...core.console import reveal
from ...errors import ToolkitError
from .. import DEFAULT_PORT, content, workspaces
from ..context import CONTEXT
from .settings_form import settings_form

HREF = "/settings"


def settings_page() -> None:
    from .common import shell

    with shell(HREF, needs_workspace=False, settings_open=True):
        ui.label("Settings are in the panel on the right.").classes("text-sm opacity-70")
        ui.label("You can open it from any page with the gear in the top right corner.") \
            .classes("text-xs opacity-60")


def settings_body(active: str = "/"):
    """Everything in the drawer. `active` is the page it is open on, so a job started here
    reports back to a panel the user is actually looking at.

    Returns the work to do when the drawer is actually opened. The drawer is built on every
    page, and the version check is a call to GitHub — doing that on every page load would put
    a network round trip behind every click in the app.
    """
    _project()
    on_open = _version(active)
    _desktop_app()
    _files()
    _delete_project()
    _quit()
    return on_open


def _card(title: str, blurb: str = ""):
    ui.label(title).classes("text-sm font-medium mt-3")
    if blurb:
        ui.label(blurb).classes("text-xs opacity-70")
    return ui.card().classes("w-full")


def _project() -> None:
    if CONTEXT.project is None:
        return
    with _card("This project", "What it is called, wherever the app shows it."):
        settings_form(config_settings.PROJECT, note=False,
                      save_label="Save the project name")
        ui.label("Settings that belong to one step — which model it uses, how hard it thinks — "
                 "are on that step's own page.").classes("text-xs opacity-60")


def _version(active: str):
    from .common import launch_global

    with _card("Version"):
        ui.label(f"transcript-toolkit {__version__}").classes("text-sm font-medium")
        notice = ui.label().classes("text-xs opacity-60")

        async def check() -> None:
            from ...core.update import update_notice
            notice.text = "checking for a newer version…"
            # A network call, so off the main thread: a slow or unreachable GitHub must never
            # make the panel hang.
            message = await run.io_bound(update_notice)
            notice.text = message.strip() if message else "This is the latest version."
            notice.classes(replace="text-xs opacity-80 whitespace-pre-line")

        ui.button("Update to the most recent version", icon="system_update",
                  on_click=lambda: launch_global(content.UPDATE_TITLE, ["update"], active)) \
            .props("dense flat")
        ui.label("If there is a newer version, the toolkit installs it and then starts again on "
                 "it — this page goes quiet for a few seconds and comes back by itself. Nothing "
                 "in your projects is touched.").classes("text-xs opacity-60")
    return check


def _desktop_app() -> None:
    if sys.platform != "darwin":
        return
    from ..launcher import app_path, log_path
    from .common import guard

    with _card("Desktop app", "A double-clickable app that starts this window."):
        exists = app_path().exists()
        ui.label(f"{app_path()}" + ("" if exists else "  (not created yet)")) \
            .classes("text-xs break-all" if exists else "text-xs break-all opacity-70")

        def install() -> None:
            from ..launcher import install_launcher, where_to_find
            try:
                path = install_launcher(port=None if CONTEXT.port == DEFAULT_PORT else CONTEXT.port)
            except ToolkitError as e:
                guard(e)
                return
            ui.notify(f"Created {path}.\n\n{where_to_find(path)}",
                      type="positive", multi_line=True, close_button="OK",
                      classes="max-w-xl whitespace-pre-line")

        ui.button("Create it again" if exists else "Create the app", icon="apps",
                  on_click=install).props("dense")
        ui.label(f"Startup messages go to {log_path()}").classes("text-xs opacity-60 break-all")


def _files() -> None:
    """Where the settings this app does not show are kept. Everything the toolkit reads is a file
    in the project folder, and somebody who prefers editing them can."""
    project = CONTEXT.project
    if project is None:
        return
    with _card("The project's files"):
        ui.label("Every setting is a line in config.yaml; the rarely-needed ones are in "
                 "advanced/. The interviews are in data/, the results in outputs/, the review "
                 "pages in diags/.").classes("text-xs opacity-80")
        ui.label(str(project.root)).classes("text-xs opacity-60 break-all")
        ui.button("Show in Finder", icon="folder_open",
                  on_click=lambda: reveal(project.root)).props("dense flat")


CONFIRM_WORD = "DELETE"


def _delete_project() -> None:
    project = CONTEXT.project
    if project is None:
        return
    with _card("Delete this project",
               "Removes the whole project folder: the transcripts in it, everything the "
               "toolkit made from them, and its settings."):
        ui.label(str(project.root)).classes("text-xs opacity-60 break-all")
        ui.button("Delete this project", icon="delete_forever",
                  on_click=lambda: _confirm_delete(project)).props("dense outline color=negative")


def _confirm_delete(project) -> None:
    from .common import guard

    counts = workspaces.describe(project)
    with ui.dialog() as dialog, ui.card().classes("max-w-md"):
        ui.label("Delete this project?").classes("text-lg font-medium")
        ui.label(str(project.root)).classes("text-xs font-mono opacity-70 break-all")
        ui.label(f"{counts['transcripts']} transcript"
                 f"{'s' if counts['transcripts'] != 1 else ''}, "
                 f"{counts['results']} result file{'s' if counts['results'] != 1 else ''} and "
                 f"{counts['review pages']} review page"
                 f"{'s' if counts['review pages'] != 1 else ''} go with it.").classes("text-sm")
        if sys.platform == "darwin":
            ui.label("It goes to the Trash, so you can put it back if this was a mistake.") \
                .classes("text-xs opacity-70")
        ui.label(f"Type {CONFIRM_WORD} to confirm.").classes("text-sm mt-2")
        field = ui.input(label=CONFIRM_WORD).classes("w-full")

        def go() -> None:
            if field.value.strip() != CONFIRM_WORD:
                guard(ToolkitError(f"Type {CONFIRM_WORD} exactly, or press Cancel."))
                return
            if CONTEXT.jobs.busy:
                guard(ToolkitError(f"'{CONTEXT.jobs.current.title}' is still running in this "
                                   f"project. Stop it first."))
                return
            try:
                where = workspaces.delete_project(project)
            except ToolkitError as e:
                guard(e)
                return
            CONTEXT.close()
            dialog.close()
            ui.notify(f"Deleted. It is in {where}.", type="warning", close_button="OK")
            ui.navigate.to("/")

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat dense")
            ui.button("Delete it", on_click=go).props("dense color=negative")
    dialog.open()


def _quit() -> None:
    from .common import guard

    with _card("Quit"):
        ui.label("The toolkit keeps running in the background after you close this tab — that is "
                 "how a long run survives a closed window. Quit it when you are done, or after "
                 "installing an update.").classes("text-xs opacity-80")

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
