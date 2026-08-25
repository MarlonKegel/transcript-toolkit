"""The workspace page: one project, from a folder of Word files to a pipeline you can run.

Everything about the open project is here — what to do next, its transcripts, the interviews the
demos run on, and the pipeline itself. The list of projects is Home; this is one of them.
"""
from __future__ import annotations

from nicegui import ui

from ...errors import ToolkitError
from .. import content, stage, theme, workspaces
from ..context import CONTEXT
from .browse import choose_folder
from .common import (guard, run_status, section, shell, shown_name, status_chip,
                     terminal_viewer)
from .sample import BLURB as SAMPLE_BLURB
from .sample import TITLE as SAMPLE_TITLE
from .sample import sample_section
from .spend import cost_report
from .transcripts import transcripts_section

HREF = "/workspace"


def workspace_page() -> None:
    with shell(HREF, needs_workspace=False):
        if CONTEXT.missing is not None:
            _gone()
            return
        if CONTEXT.project is None:
            _nothing_open()
            return

        def refresh_all() -> None:
            body.refresh()
            rest.refresh()

        @ui.refreshable
        def body() -> None:
            _next_step()
            _pipeline()
            _api_key(refresh_all)
            transcripts_section(refresh_all)
            _demo_sample(refresh_all)
            _cost()

        @ui.refreshable
        def rest() -> None:
            _folder()

        body()
        # Directly below the two things on this page that start a command — importing and
        # picking the demo interviews — rather than at the foot of the page.
        run_status(on_finished=refresh_all)
        rest()
        terminal_viewer()


def _nothing_open() -> None:
    section("No project open")
    with ui.card().classes("w-full"):
        ui.label("Pick one on the home page, or start a new one there.").classes("text-sm")
        ui.button("Go to your projects", icon="home",
                  on_click=lambda: ui.navigate.to("/")).props("dense")


def _gone() -> None:
    """The project that was open is not where it was.

    Somebody renamed it, moved it to another disk, or threw it away — from Finder, with no idea
    the app had it open. Both are ordinary things to have done, so this asks which rather than
    guessing, and neither answer loses anything.
    """
    missing = CONTEXT.missing
    with ui.card().classes(f"w-full {theme.WARN}"):
        ui.label("Your project is not where it was").classes("text-lg font-medium")
        ui.label(str(missing)).classes("text-xs font-mono opacity-70 break-all")
        ui.label("Nothing has been lost by the toolkit — it only stopped finding the folder "
                 "there.").classes("text-sm")

        def moved(path: str) -> None:
            try:
                CONTEXT.open(workspaces.open_workspace(path))
            except ToolkitError as e:
                guard(e)
                return
            CONTEXT.missing = None
            workspaces.forget(str(missing))         # the old path will never work again
            ui.navigate.to(HREF)

        def deleted() -> None:
            workspaces.forget(str(missing))
            CONTEXT.close()
            ui.navigate.to("/")

        with ui.row().classes("gap-2 flex-wrap"):
            ui.button("I moved or renamed it", icon="drive_file_move",
                      on_click=lambda: choose_folder(
                          moved, start=missing.parent,
                          title="Where is it now?",
                          hint="Open the project folder itself, then use it.")).props("dense")
            ui.button("I deleted it", icon="delete_outline", on_click=deleted) \
                .props("dense flat")


def _status_and_sets() -> tuple[dict, list[str]]:
    status = CONTEXT.status()
    try:
        sets = CONTEXT.topic_sets()
    except ToolkitError:
        sets = []
    return status, sets


def _next_step() -> None:
    project = CONTEXT.require_project()
    try:
        status, sets = _status_and_sets()
    except ToolkitError as e:
        guard(e)
        return
    title, why, href = stage.next_action(status, project, sets)
    with ui.card().classes("w-full bg-primary text-white"):
        ui.label("Next").classes("text-xs uppercase opacity-70")
        ui.label(title).classes("text-2xl font-medium")
        ui.label(why).classes("text-sm opacity-90")
        ui.button("Go", icon="arrow_forward", on_click=lambda: ui.navigate.to(href)) \
            .props("outline color=white dense").classes("mt-1 self-start")


def _pipeline() -> None:
    try:
        project = CONTEXT.require_project()
        status, sets = _status_and_sets()
    except ToolkitError as e:
        guard(e)
        return
    section("The pipeline", "Each step is demo-first: try it on a few interviews, read the "
                            "result, then run the whole corpus.")
    with ui.column().classes("w-full gap-2"):
        for step in content.STEPS:
            set_name = sets[0] if (step.per_set and sets) else None
            word, colour = stage.step_state(status, step, set_name, project)
            with ui.card().classes("w-full py-3"):
                with ui.row().classes("items-center w-full gap-3"):
                    ui.label(str(step.order)).classes("text-sm opacity-40 w-4 text-right")
                    with ui.column().classes("gap-0 grow"):
                        ui.link(step.title, f"/step/{step.slug}") \
                            .classes("text-base font-medium no-underline")
                        ui.label(step.blurb).classes("text-xs opacity-70")
                    status_chip(word, colour)


def _rename(project, refresh) -> None:
    """Projects made before the toolkit derived the name are all called the same thing. This
    is the one-field fix, so nobody has to be told to edit config.yaml."""
    with ui.row().classes("w-full items-end gap-2"):
        field = ui.input("Project name", value=shown_name(project)).classes("grow")

        def save() -> None:
            try:
                workspaces.rename_project(project, field.value)
            except ToolkitError as e:
                guard(e)
                return
            refresh()

        ui.button("Save", on_click=save).props("dense")


def _api_key(refresh) -> None:
    """The key lives with the project, and nothing runs without it — so it is on the page that
    gets a project started, not behind the gear with the settings."""
    project = CONTEXT.require_project()
    if workspaces.has_api_key(project):
        with ui.expansion("OpenAI key — saved", icon="key").classes("w-full"):
            ui.label("Runs are billed to whoever owns it. Replace it below if it changes.") \
                .classes("text-xs opacity-70")
            _key_field(project, refresh)
        return
    section("OpenAI key")
    with ui.card().classes(f"w-full {theme.WARN}"):
        ui.label("No key yet — nothing can run without one.").classes("text-sm font-medium")
        ui.label("Ask whoever administers your team's OpenAI account for one.") \
            .classes("text-xs opacity-80")
        _key_field(project, refresh)


def _key_field(project, refresh) -> None:
    field = ui.input("Paste a key", password=True, placeholder="sk-...").classes("w-full")

    def save() -> None:
        try:
            workspaces.set_api_key(project, field.value)
        except ToolkitError as e:
            guard(e)
            return
        refresh()

    ui.button("Save key", icon="key", on_click=save).props("dense")
    ui.label("It is stored in this project's .env file and never leaves your Mac except "
             "in calls to OpenAI.").classes("text-xs opacity-60")


def _demo_sample(refresh) -> None:
    """The demo interviews live here, with the project — every step's demo uses them."""
    if not CONTEXT.require_project().paragraphs_path.exists():
        return
    section(SAMPLE_TITLE, SAMPLE_BLURB)
    sample_section(HREF, refresh)


def _cost() -> None:
    """What this project has cost. It belongs to the project rather than to a step, and it is the
    question somebody asks before starting the next expensive thing."""
    ui.link_target("cost")
    section("Project cost report", "Everything this project has been billed for so far, demos "
                                   "included. It goes up whenever something runs.")
    cost_report()


def _folder() -> None:
    from ...core.console import reveal

    project = CONTEXT.require_project()
    with ui.expansion("This project's folder", icon="folder_open").classes("w-full"):
        ui.label(str(project.root)).classes("text-xs font-mono opacity-70 break-all")
        ui.label("Everything the toolkit makes is in here: results in outputs/, review pages in "
                 "diags/, settings in config.yaml.").classes("text-xs opacity-70")
        with ui.row().classes("gap-2 items-center"):
            ui.button("Show in Finder", icon="folder_open",
                      on_click=lambda: reveal(project.root)).props("dense flat")
        ui.label("Rename the project").classes("text-sm font-medium mt-2")
        ui.label("Changes what it is called. Its folder keeps the name it has — rename that in "
                 "Finder if you want to.").classes("text-xs opacity-70")

        def refresh() -> None:
            ui.navigate.to(HREF)

        _rename(project, refresh)


def register() -> None:
    ui.page(HREF, title="Workspace — Transcript Toolkit")(workspace_page)
