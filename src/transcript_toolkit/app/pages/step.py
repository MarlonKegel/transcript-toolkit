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
from .. import content, topic_lists
from ..context import CONTEXT
from .common import guard, info, launch, run_panel, section, shell
from .sample import needed_here, sample_section
from .topics_editor import editor

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
            _sample(step, href, body.refresh)
            _actions(step, set_name, href)
            _reviews(project, step, set_name)
            _sequels(step, set_name, href)
            _followups(step, set_name, href)
            if step.per_set and set_name:
                _edit_set(step, project, set_name)
            _advanced(step, set_name, href)

        body()
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
            ui.label("A topic list is one row per topic: a name and a description of what "
                     "belongs under it. Write it here, or bring one you already have.") \
                .classes("text-sm opacity-80")
            with ui.tabs().classes("w-full") as tabs:
                write_tab = ui.tab("Write one here")
                upload_tab = ui.tab("Upload a spreadsheet")
            with ui.tab_panels(tabs, value=write_tab).classes("w-full"):
                with ui.tab_panel(write_tab):
                    editor(None, topic_lists.draft_path(project),
                           lambda name: ui.navigate.to(f"{href_for(step)}?{SET_QUERY}={name}"))
                with ui.tab_panel(upload_tab):
                    _topic_upload(step, project)
        return None

    current = chosen if chosen in sets else sets[0]
    if len(sets) > 1:
        with ui.row().classes("items-center gap-2"):
            ui.label("Topic list").classes("text-sm opacity-70")
            ui.select(sets, value=current,
                      on_change=lambda e: ui.navigate.to(
                          f"{href_for(step)}?{SET_QUERY}={e.value}")).props("dense outlined")
    return current


def _topic_upload(step: content.Step, project) -> None:
    async def receive(e) -> None:
        added = []
        for upload in e.files:
            name = Path(upload.name).name
            if Path(name).suffix.lower() not in (".csv", ".xlsx"):
                guard(ToolkitError(f"{name} is not a spreadsheet. A topic list has to be a "
                                   f".csv or .xlsx file."))
                continue
            dest = project.topics_dir / name
            if dest.exists():
                guard(ToolkitError(f"There is already a topic list called {name} in this "
                                   f"project, so it was not added again. To replace it, delete "
                                   f"the one in {project.topics_dir} first."))
                continue
            project.topics_dir.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(await upload.read())
            added.append(dest.stem)
        if added:
            ui.notify(f"Added {', '.join(added)}.", type="positive")
            ui.navigate.to(f"{href_for(step)}?{SET_QUERY}={added[0]}")

    ui.label("Two columns are needed: `name` and `description`, one row per topic. The "
             "filename becomes the list's name, so collection.csv is the list 'collection'.") \
        .classes("text-sm opacity-80")
    ui.upload(on_multi_upload=receive, multiple=True, auto_upload=True,
              label="Drop a topic list here").props("accept=.csv,.xlsx flat bordered") \
        .classes("w-full")
    ui.label(f"Or put one in {project.topics_dir} yourself.").classes("text-xs opacity-60")


def _edit_set(step: content.Step, project, set_name: str) -> None:
    """Change a list that is already in use, without leaving the app."""
    from ...core.config import load_root_config

    entry = ((load_root_config(project).get("topics") or {}).get("sets") or {}).get(set_name) or {}
    path = (project.root / entry["file"]) if entry.get("file") else \
        topic_lists.set_path(project, set_name)
    with ui.expansion("Edit this topic list", icon="edit").classes("w-full"):
        if path.suffix.lower() != ".csv" or not path.exists():
            ui.label(f"'{set_name}' is kept in {path.name}, which is not edited here. Change it "
                     f"in Excel, or upload a replacement under a new name.") \
                .classes("text-sm opacity-80")
            return
        ui.label("Changing a topic list changes what the tags mean, so the next full run will "
                 "ask you to try it out and review it again first.") \
            .classes("text-xs opacity-70 max-w-2xl")
        editor(set_name, path, lambda _: ui.navigate.to(f"{href_for(step)}?{SET_QUERY}={set_name}"))


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


def _sample(step: content.Step, href: str, refresh) -> None:
    """Clip and label demos run on a fixed handful of interviews, chosen once. Offer the whole
    chooser here rather than letting the first demo fail for want of it — but the choice itself
    belongs to the project, so this is the workspace page's section, borrowed."""
    if not step.needs_sample or not needed_here(step):
        return
    with ui.card().classes("w-full bg-blue-50 dark:bg-blue-900/30"):
        ui.label("You have not chosen the demo interviews yet.").classes("text-sm font-medium")
        ui.label("Choose them before you try this step out — every step's demo runs on the "
                 "same few interviews, so what you read is comparable.") \
            .classes("text-xs opacity-80 max-w-2xl")
        ui.link("They can also be changed on the workspace page.", "/workspace") \
            .classes("text-xs")
    sample_section(href, refresh)


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


def _run_button(step: content.Step, action: content.Action, set_name: str | None, href: str,
                *, flat: bool = False) -> None:
    """A Run button that is only clickable when what it reads actually exists."""
    missing = content.missing_for(action, _status()["deliverables"], set_name)
    button = ui.button("Run", on_click=lambda _, a=action: launch(
        f"{step.title} — {a.title.lower()}",
        content.action_argv(a, set_name), href)).props("dense" + (" flat" if flat else ""))
    if missing:
        button.disable()
        button.tooltip(f"Nothing to work from yet — this reads the "
                       f"{', '.join(m.split(':')[0] for m in missing)} that "
                       f"'{step.title}' produces. Run this step first.")


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
                _run_button(step, action, set_name, href)


def _followups(step: content.Step, set_name: str | None, href: str) -> None:
    ordinary = [a for a in step.followups if not a.advanced]
    if not ordinary:
        return
    with ui.expansion("Other things this step can do", icon="tune").classes("w-full"):
        for action in ordinary:
            with ui.row().classes("items-center w-full gap-3 py-1"):
                with ui.column().classes("gap-0 grow"):
                    ui.label(action.title).classes("text-sm font-medium")
                    ui.label(action.blurb).classes("text-xs opacity-70")
                _run_button(step, action, set_name, href, flat=True)


def _advanced(step: content.Step, set_name: str | None, href: str) -> None:
    """Things that explain how the step works rather than change what it does. Out of the way
    by default: nobody needs to understand chunking to clip an interview."""
    advanced = [a for a in step.followups if a.advanced]
    if not advanced:
        return
    with ui.expansion("Advanced", icon="settings").classes("w-full"):
        ui.label("Nothing here is needed to run the step. It is here if you want to see how "
                 "the work is divided up, or to dig into how it behaves.") \
            .classes("text-xs opacity-70 max-w-2xl")
        for action in advanced:
            with ui.column().classes("w-full gap-1 py-2"):
                with ui.row().classes("items-center w-full gap-2"):
                    ui.label(action.title).classes("text-sm font-medium")
                    if action.explain:
                        info(action.explain)
                    ui.space()
                    if action.preview:
                        _preview_button(action, set_name)
                    else:
                        _run_button(step, action, set_name, href, flat=True)
                ui.label(action.blurb).classes("text-xs opacity-70 max-w-2xl")
                if action.preview:
                    ui.label("You can also run this in Terminal: "
                             f"{content.display_command(content.action_argv(action, set_name))}") \
                        .classes("text-xs opacity-50 font-mono")


PREVIEWS = {
    # name -> (function that reads the workspace, column definitions)
    "chunks": ("How each interview will be split", (
        ("interview_id", "Interview"), ("n_para", "Paragraphs"),
        ("est_total_tokens", "Est. size"), ("n_chunks", "Pieces"), ("layout", "Layout"))),
    "batches": ("How clips will be grouped", (
        ("interview_id", "Interview"), ("n_clips", "Clips"),
        ("tot_tokens", "Est. size"), ("n_batches", "Groups"), ("layout", "Layout"))),
}


def _preview_data(kind: str, project) -> dict:
    from ...steps.clip import chunk_preview
    from ...steps.label import batch_preview

    return {"chunks": chunk_preview, "batches": batch_preview}[kind](project)


def _preview_button(action: content.Action, set_name: str | None) -> None:
    """Show the preview in the app. It reads the workspace and makes no API calls, so there is
    nothing to run as a job — the same numbers `toolkit ... preview` prints, as a table."""
    async def show() -> None:
        import asyncio

        project = CONTEXT.require_project()
        try:
            data = await asyncio.to_thread(_preview_data, action.preview, project)
        except ToolkitError as e:
            guard(e)
            return
        _preview_dialog(action, data)

    ui.button("Show", icon="table_chart", on_click=show).props("dense outline")


def _preview_dialog(action: content.Action, data: dict) -> None:
    title, columns = PREVIEWS[action.preview]
    with ui.dialog().props("full-width") as dialog, ui.card().classes("w-full"):
        with ui.row().classes("items-center gap-2 w-full"):
            ui.label(title).classes("text-lg font-medium")
            if action.explain:
                info(action.explain)
            ui.space()
            ui.button(icon="close", on_click=dialog.close).props("flat dense round")
        counts = ", ".join(f"{count} interview{'s' if count != 1 else ''} in {n} "
                           f"piece{'s' if n != 1 else ''}"
                           for n, count in data["distribution"].items())
        ui.label(counts).classes("text-sm opacity-80")
        ui.table(columns=[{"name": name, "label": label, "field": name,
                           "align": "right" if name != "interview_id" and name != "layout"
                                    else "left"}
                          for name, label in columns],
                 rows=data["rows"], row_key="interview_id") \
            .props("dense flat wrap-cells").classes("w-full")
        ui.label("'Layout' is the detail: where each piece starts and ends, and roughly how "
                 "big it is. You do not need to read it.").classes("text-xs opacity-60")
    dialog.open()


def register() -> None:
    ui.page("/step/{slug}")(step_page)
