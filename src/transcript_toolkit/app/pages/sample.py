"""Choosing the interviews the demos run on.

Every demo in the pipeline runs on the same handful of interviews, chosen once, so that what you
read after the clip demo and what you read after the label demo are about the same people. That
choice belongs with the workspace — it is a property of the project, not of one step — so this
section lives on the workspace page, and steps that need it borrow the same section.

Every change here runs `toolkit sample` with the interviews it should end up with, so the file
that records the choice is written by the toolkit and not by the app.
"""
from __future__ import annotations

from nicegui import ui

from ...errors import ToolkitError
from .. import content, workspaces
from ..context import CONTEXT
from .common import guard, launch

TITLE = "Pick the sample of interviews for demos"
BLURB = ("Trying a step out runs it on these interviews only. The same few are used by every "
         "step, so what you read is comparable.")


def current_sample(project) -> list[str]:
    """The interviews demos currently run on, or an empty list if none have been chosen."""
    if not project.demo_sample_path.exists():
        return []
    return [line.strip() for line in project.demo_sample_path.read_text().splitlines()
            if line.strip()]


def sample_section(href: str, refresh=None) -> None:
    project = CONTEXT.require_project()
    chosen = current_sample(project)
    available = sorted(workspaces.imported_ids(project))

    with ui.card().classes("w-full"):
        if not available:
            ui.label("No demo interviews chosen yet.").classes("text-sm font-medium")
            ui.label("Import your transcripts first — the choice is made from them.") \
                .classes("text-xs opacity-70")
            return

        async def apply(interviews: list[str], n: int | None = None) -> None:
            """Set the sample to exactly `interviews`, or to `n` with those in it — asking for
            more than are named is how `toolkit sample` fills the rest at random."""
            await launch(content.SAMPLE.title,
                         content.sample_argv(n or len(interviews), interviews), href)
            if refresh:
                refresh()

        if chosen:
            _chosen_list(chosen, available, apply)
            with ui.expansion("Start the selection again", icon="casino").classes("w-full"):
                _chooser(available, chosen, href, refresh)
        else:
            ui.label("No demo interviews chosen yet.").classes("text-sm font-medium")
            ui.label(BLURB).classes("text-xs opacity-70 max-w-2xl")
            _chooser(available, chosen, href, refresh)


def _chosen_list(chosen: list[str], available: list[str], apply) -> None:
    """The interviews that were picked, one per line, each removable."""
    with ui.row().classes("items-center gap-2"):
        ui.icon("check_circle").classes("tk-good")
        ui.label(f"Demos run on these {len(chosen)} interview"
                 f"{'s' if len(chosen) != 1 else ''}:").classes("text-sm font-medium")
    with ui.column().classes("w-full gap-0"):
        for interview in chosen:
            with ui.row().classes("items-center gap-2 w-full py-0.5 tk-row"):
                ui.label(interview).classes("text-xs font-mono grow truncate")
                remove = ui.button(icon="close",
                                   on_click=lambda _, i=interview: apply(
                                       [c for c in chosen if c != i])) \
                    .props("flat dense round")
                if len(chosen) <= content.SAMPLE_MIN_N:
                    remove.disable()
                    remove.tooltip(f"A demo runs on at least {content.SAMPLE_MIN_N} interviews. "
                                   f"Add another one first, or start the selection again.")
                else:
                    remove.tooltip("Take this one out of the demo sample")

    room = content.SAMPLE_MAX_N - len(chosen)
    rest = [i for i in available if i not in chosen]
    if not room or not rest:
        ui.label(f"That is as many as a demo runs on ({content.SAMPLE_MAX_N} at most)."
                 if not room else
                 "Every imported interview is in the sample.").classes("text-xs opacity-60")
        return

    with ui.row().classes("items-end gap-2 flex-wrap mt-2"):
        how_many = ui.number("Add this many at random", value=1, min=1, max=min(room, len(rest)),
                             step=1, precision=0).props("dense outlined").classes("w-52")
        ui.button("Add them", icon="casino",
                  on_click=lambda: apply(chosen, len(chosen) + int(how_many.value or 1))) \
            .props("dense flat")
    with ui.row().classes("items-end gap-2 flex-wrap"):
        one = ui.select(rest, label="Or add a particular interview", with_input=True) \
            .props("dense outlined").classes("grow min-w-64")

        def add_one() -> None:
            if not one.value:
                guard(ToolkitError("Pick which interview to add first."))
                return
            ui.timer(0, lambda: apply(sorted({*chosen, one.value})), once=True)

        ui.button("Add it", icon="add", on_click=add_one).props("dense flat")


def _chooser(available: list[str], chosen: list[str], href: str, refresh) -> None:
    """How many, and whether the toolkit picks them or you do."""
    ceiling = min(content.SAMPLE_MAX_N, len(available))
    floor = min(content.SAMPLE_MIN_N, len(available))
    size = ui.number("How many interviews", value=min(max(len(chosen) or
                                                          content.SAMPLE_DEFAULT_N, floor),
                                                      ceiling),
                     min=floor, max=ceiling, step=1, precision=0) \
        .props("dense outlined").classes("w-56")
    ui.label(f"Between {floor} and {ceiling}. {content.SAMPLE_DEFAULT_N} is the usual number — "
             f"you do not have to pick all of them.").classes("text-xs opacity-70")

    how = ui.radio({"random": "Draw them at random",
                    "pick": "Choose the interviews myself"}, value="random") \
        .props("inline dense")

    picked = ui.select(available, multiple=True, value=[i for i in chosen if i in available],
                       label="Interviews to include") \
        .props("dense outlined use-chips").classes("w-full")

    cost_note = ui.label().classes("text-xs tk-caution max-w-2xl")
    pick_note = ui.label().classes("text-xs opacity-70 max-w-2xl")

    def review() -> None:
        picked.set_visibility(how.value == "pick")
        n = int(size.value or content.SAMPLE_DEFAULT_N)
        # Over the usual number, say what it costs before they run it, not after.
        cost_note.set_text(
            f"Every demo run from here on costs about {n / content.SAMPLE_DEFAULT_N:.1f}× what "
            f"it would with {content.SAMPLE_DEFAULT_N}." if n > content.SAMPLE_DEFAULT_N else "")
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
        if n > ceiling:
            guard(ToolkitError(f"A demo runs on at most {content.SAMPLE_MAX_N} interviews."))
            return
        await launch(content.SAMPLE.title, content.sample_argv(n, interviews), href)
        if refresh:
            refresh()

    ui.button("Pick the demo interviews", icon="casino", on_click=draw).props("dense")
    ui.label("Choosing again replaces the current set. Demos you have already run stay where "
             "they are; the next one uses the new interviews.").classes("text-xs opacity-60")


def needed_here(step: content.Step) -> bool:
    """Whether this step's demo cannot run until interviews have been chosen."""
    return step.needs_sample and not current_sample(CONTEXT.require_project())
