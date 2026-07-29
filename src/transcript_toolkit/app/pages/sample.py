"""Choosing the interviews the demos run on.

Every demo in the pipeline runs on the same handful of interviews, chosen once, so that what
you read after the clip demo and what you read after the label demo are about the same people.
That choice belongs with the workspace — it is a property of the project, not of one step — so
this section lives on the workspace page, and steps that need it borrow the same section.
"""
from __future__ import annotations

from nicegui import ui

from ...errors import ToolkitError
from .. import content, workspaces
from ..context import CONTEXT
from .common import guard, launch


def current_sample(project) -> list[str]:
    """The interviews demos currently run on, or an empty list if none have been chosen."""
    if not project.demo_sample_path.exists():
        return []
    return [line.strip() for line in project.demo_sample_path.read_text().splitlines()
            if line.strip()]


def sample_section(href: str, refresh=None) -> None:
    """The chooser: random or hand-picked, and how many."""
    project = CONTEXT.require_project()
    chosen = current_sample(project)
    available = sorted(workspaces.imported_ids(project))

    with ui.card().classes("w-full"):
        if chosen:
            with ui.row().classes("items-center gap-2"):
                ui.icon("check_circle").classes("text-green-600")
                ui.label(f"Demos run on {len(chosen)} interview"
                         f"{'s' if len(chosen) != 1 else ''}:").classes("text-sm font-medium")
            ui.label(", ".join(chosen)).classes("text-xs opacity-80 break-all")
        else:
            ui.label("No demo interviews chosen yet.").classes("text-sm font-medium")
            ui.label(content.SAMPLE.blurb).classes("text-xs opacity-70 max-w-2xl")

        if not available:
            ui.label("Import your transcripts first — the choice is made from them.") \
                .classes("text-xs opacity-70")
            return

        with ui.expansion("Choose them again" if chosen else "Choose them",
                          icon="casino", value=not chosen).classes("w-full"):
            _chooser(available, chosen, href, refresh)


def _chooser(available: list[str], chosen: list[str], href: str, refresh) -> None:
    how = ui.radio({"random": "Draw them at random",
                    "pick": "Choose the interviews myself"}, value="random") \
        .props("inline dense")

    size = ui.number("How many", value=content.SAMPLE_DEFAULT_N, min=1,
                     max=min(content.SAMPLE_MAX_N, len(available)), step=1, precision=0) \
        .props("dense outlined").classes("w-40")

    picked = ui.select(available, multiple=True, value=[i for i in chosen if i in available],
                       label="Interviews to include") \
        .props("dense outlined use-chips").classes("w-full")

    cost_note = ui.label().classes("text-xs text-amber-700 dark:text-amber-400 max-w-2xl")
    pick_note = ui.label().classes("text-xs opacity-70 max-w-2xl")

    def review() -> None:
        picked.set_visibility(how.value == "pick")
        n = int(size.value or content.SAMPLE_DEFAULT_N)
        # Over the default, say what it costs before they run it, not after.
        cost_note.set_text(
            f"{content.SAMPLE_DEFAULT_N} is the usual number. You can go up to "
            f"{content.SAMPLE_MAX_N}, but every demo run from here on costs about "
            f"{n / content.SAMPLE_DEFAULT_N:.1f}× what it would with "
            f"{content.SAMPLE_DEFAULT_N}." if n > content.SAMPLE_DEFAULT_N else "")
        extra = n - len(picked.value or [])
        pick_note.set_text(
            f"{len(picked.value)} chosen; the other {extra} will be drawn at random."
            if how.value == "pick" and extra > 0 else
            f"{len(picked.value)} chosen — that is the whole sample."
            if how.value == "pick" and picked.value else "")

    how.on_value_change(review)
    size.on_value_change(review)
    picked.on_value_change(review)
    review()

    async def draw() -> None:
        n = int(size.value or content.SAMPLE_DEFAULT_N)
        interviews = list(picked.value or []) if how.value == "pick" else None
        if how.value == "pick" and not interviews:
            guard(ToolkitError("Pick at least one interview, or switch back to a random draw."))
            return
        if interviews and len(interviews) > n:
            n = len(interviews)         # naming more than the size asked for means you want them
        await launch(content.SAMPLE.title, content.sample_argv(n, interviews), href)
        if refresh:
            refresh()

    ui.button(content.SAMPLE.title, icon="casino", on_click=draw).props("dense")
    ui.label("Choosing again replaces the current set. Demos you have already run stay where "
             "they are; the next one uses the new interviews.").classes("text-xs opacity-60")


def needed_here(step: content.Step) -> bool:
    """Whether this step's demo cannot run until interviews have been chosen."""
    return step.needs_sample and not current_sample(CONTEXT.require_project())
