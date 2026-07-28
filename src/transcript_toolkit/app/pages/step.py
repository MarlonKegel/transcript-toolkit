"""One page per pipeline step, all from the same template.

The shape of every step is the same — try it on a few interviews, read what came out, then run
the whole collection — so the page is the same too, and `content.py` supplies the differences.

Everything below the buttons is rebuilt when a run finishes: a review page that did not exist
when the page loaded is exactly the thing the user is then supposed to open.
"""
from __future__ import annotations

from pathlib import Path

from nicegui import ui

from ...errors import ToolkitError
from .. import content
from ..context import CONTEXT
from .common import guard, launch, run_panel, section, shell

SET_QUERY = "set"


def href_for(step: content.Step) -> str:
    return f"/step/{step.slug}"


def step_page(slug: str, set: str | None = None) -> None:      # noqa: A002 - URL query name
    step = content.BY_SLUG.get(slug)
    if step is None:
        with shell(needs_workspace=False):
            ui.label(f"No step called {slug!r}.").classes("text-lg")
        return

    href = href_for(step)
    with shell(href):
        if CONTEXT.project is None:
            return
        ui.page_title(f"{step.title} — Transcript Toolkit")
        project = CONTEXT.require_project()

        set_name = None
        if step.per_set:
            set_name = _topic_sets(step, set)
            if set_name is None:
                return

        section(step.title, step.blurb)

        @ui.refreshable
        def body() -> None:
            _prerequisites(step)
            _sample(step, href)
            _actions(step, set_name, href)
            _reviews(project, step, set_name)
            _sequels(step, set_name, href)

        body()
        _followups(step, set_name, href)
        run_panel(on_fix=lambda kind: _fix(kind, step, set_name, href),
                  on_finished=body.refresh)


def _fix(kind: str, step: content.Step, set_name: str | None, href: str) -> None:
    if kind == "sample":
        ui.timer(0, lambda: launch(content.SAMPLE.title, list(content.SAMPLE.argv), href),
                 once=True)
    else:
        ui.timer(0, lambda: launch(f"{step.title} — demo",
                                   content.run_argv(step, demo=True, set_name=set_name), href),
                 once=True)


def _topic_sets(step: content.Step, chosen: str | None) -> str | None:
    """The set picker. Topic lists are just spreadsheets in topics/ — the filename is the name."""
    project = CONTEXT.require_project()
    try:
        sets = CONTEXT.topic_sets()
    except ToolkitError as e:
        guard(e)
        return None

    if not sets:
        section(step.title, step.blurb)
        with ui.card().classes("w-full"):
            ui.label("No topic list yet.").classes("font-medium")
            ui.label("A topic list is a spreadsheet with a `name` and a `description` column — "
                     "one row per topic. Its filename becomes the set name, so "
                     "collection.csv is the set 'collection'.").classes("text-sm opacity-80")

            async def receive(e) -> None:
                name = Path(e.file.name).name
                if Path(name).suffix.lower() not in (".csv", ".xlsx"):
                    guard(ToolkitError(f"{name} is not a .csv or .xlsx file."))
                    return
                project.topics_dir.mkdir(parents=True, exist_ok=True)
                dest = project.topics_dir / name
                if dest.exists():
                    guard(ToolkitError(
                        f"There is already a topics/{name}. Rename the new one, or remove the "
                        f"old one first — replacing it would change what the tags mean."))
                    return
                dest.write_bytes(await e.file.read())
                ui.notify(f"Added {name}", type="positive")
                ui.navigate.to(href_for(step))

            ui.upload(on_upload=receive, multiple=True, auto_upload=True,
                      label="Drop a topic list here").props("accept=.csv,.xlsx flat bordered") \
                .classes("w-full")
            ui.label(f"Or put one in {project.topics_dir} yourself.").classes("text-xs opacity-60")
        return None

    current = chosen if chosen in sets else sets[0]
    if len(sets) > 1:
        with ui.row().classes("items-center gap-2"):
            ui.label("Topic list").classes("text-sm opacity-70")
            ui.select(sets, value=current,
                      on_change=lambda e: ui.navigate.to(
                          f"{href_for(step)}?{SET_QUERY}={e.value}")).props("dense outlined")
    return current


def _status() -> dict:
    try:
        return CONTEXT.status()
    except ToolkitError as e:
        guard(e)
        return {"imported": False, "deliverables": [], "steps": {}}


def _prerequisites(step: content.Step) -> None:
    """Say plainly when an earlier step has to happen first, instead of letting the run fail."""
    status = _status()
    have = {d.split(":")[0] for d in status["deliverables"]}
    if not status["imported"]:
        with ui.card().classes("w-full bg-amber-50 dark:bg-amber-900/30"):
            ui.label("Import the transcripts first.").classes("text-sm font-medium")
            ui.link("Go to the workspace page", "/workspace").classes("text-sm")
        return
    missing = [n for n in step.needs if n not in have]
    if missing:
        with ui.card().classes("w-full bg-amber-50 dark:bg-amber-900/30"):
            ui.label(f"This step reads the {', '.join(missing)} from an earlier step. You can "
                     f"still run its demo — a demo of the previous step is enough for that.") \
                .classes("text-sm")


def _sample(step: content.Step, href: str) -> None:
    """Clip and label demos run on a fixed handful of interviews, drawn once. Offer that here
    rather than letting the first demo fail for want of it."""
    if not step.needs_sample or CONTEXT.require_project().demo_sample_path.exists():
        return
    with ui.card().classes("w-full bg-blue-50 dark:bg-blue-900/30"):
        ui.label(f"First: {content.SAMPLE.title.lower()}").classes("text-sm font-medium")
        ui.label(content.SAMPLE.blurb).classes("text-xs opacity-80 max-w-xl")
        ui.button(content.SAMPLE.title, icon="casino",
                  on_click=lambda: launch(content.SAMPLE.title, list(content.SAMPLE.argv), href)) \
            .props("dense")


def _actions(step: content.Step, set_name: str | None, href: str) -> None:
    record = _status()["steps"].get(content.step_key(step, set_name), {})
    demo, full = record.get("demo"), record.get("full")

    with ui.card().classes("w-full"):
        with ui.row().classes("w-full items-start gap-6 flex-wrap"):
            with ui.column().classes("gap-1 grow"):
                ui.label("1 · Try it").classes("text-sm font-medium")
                ui.label(f"Runs on a few {step.unit} only and writes review pages — no results "
                         f"are saved to the project.").classes("text-xs opacity-70 max-w-md")
                ui.button("Run the demo", icon="science",
                          on_click=lambda: launch(f"{step.title} — demo",
                                                  content.run_argv(step, demo=True,
                                                                   set_name=set_name), href)) \
                    .props("dense")
                if demo:
                    ui.label(f"last demo {_when(demo['at'])}").classes("text-xs opacity-60")

            with ui.column().classes("gap-1 grow"):
                ui.label("2 · Run it on everything").classes("text-sm font-medium")
                ui.label("Asks what it will cost and how to send the calls before spending "
                         "anything. Needs a demo you have reviewed first.") \
                    .classes("text-xs opacity-70 max-w-md")
                ui.button("Run on the whole collection", icon="play_arrow",
                          on_click=lambda: launch(f"{step.title} — full run",
                                                  content.run_argv(step, demo=False,
                                                                   set_name=set_name), href)) \
                    .props("dense color=primary")
                if full:
                    ui.label(f"last full run {_when(full['at'])} · {full['model']} · "
                             f"{full['n_units']} {step.unit}").classes("text-xs opacity-60")
        if step.batch:
            ui.label("A full run can go to OpenAI's Batch API at half price, taking up to a "
                     "day. You choose when it asks.").classes("text-xs opacity-60")


def _when(stamp: str) -> str:
    """A run time in the reader's own timezone — state.json records UTC."""
    from datetime import datetime, timezone
    try:
        moment = datetime.fromisoformat(stamp)
    except ValueError:
        return stamp[:16].replace("T", " ")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone().strftime("%d %b %Y, %H:%M")


def _reviews(project, step: content.Step, set_name: str | None) -> None:
    pages = diag_pages(project, step, set_name)
    if not pages:
        return
    with ui.card().classes("w-full"):
        ui.label("Review pages").classes("text-sm font-medium")
        ui.label("What the last run produced, laid out for reading. This is the part to do "
                 "before spending anything on the whole collection.").classes("text-xs opacity-70")
        with ui.row().classes("gap-3 flex-wrap"):
            for title, url in pages:
                ui.link(title, url, new_tab=True).classes("text-sm")


def diag_pages(project, step: content.Step, set_name: str | None) -> list[tuple[str, str]]:
    """Links to the review pages this step wrote. Each step names its own (content.py): they
    differ per step, and topics writes one set of pages per topic list."""
    base = project.diags_dir / step.key
    found = []
    for review in step.reviews:
        path = base / review.filename.format(set=set_name or "")
        if path.is_file():
            found.append((review.title,
                          "/diags/" + path.relative_to(project.diags_dir).as_posix()))
    return found


def _sequels(step: content.Step, set_name: str | None, href: str) -> None:
    """The steps that follow tagging in this branch of the pipeline. Part of the flow, not
    extras, so they are numbered and in plain sight."""
    if not step.sequels:
        return
    with ui.card().classes("w-full"):
        for i, action in enumerate(step.sequels, start=3):
            with ui.row().classes("items-start w-full gap-3 py-1"):
                with ui.column().classes("gap-0 grow"):
                    ui.label(f"{i} · {action.title}").classes("text-sm font-medium")
                    ui.label(action.blurb).classes("text-xs opacity-70 max-w-xl")
                ui.button("Run", on_click=lambda _, a=action: launch(
                    f"{step.title} — {a.title.lower()}",
                    content.action_argv(a, set_name), href)).props("dense")


def _followups(step: content.Step, set_name: str | None, href: str) -> None:
    if not step.followups:
        return
    with ui.expansion("Other things this step can do", icon="tune").classes("w-full"):
        for action in step.followups:
            with ui.row().classes("items-center w-full gap-3 py-1"):
                with ui.column().classes("gap-0 grow"):
                    ui.label(action.title).classes("text-sm font-medium")
                    ui.label(action.blurb).classes("text-xs opacity-70")
                ui.button("Run", on_click=lambda _, a=action: launch(
                    f"{step.title} — {a.title.lower()}",
                    content.action_argv(a, set_name), href)).props("dense flat")


def register() -> None:
    ui.page("/step/{slug}")(step_page)
