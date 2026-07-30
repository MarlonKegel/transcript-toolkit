"""One page per pipeline step, all from the same template.

The shape of every step is the same, and it is the shape of the workflow: try it on a few
interviews, read what came out, then either change something and try again or run the whole
collection. The page shows those in that order and does not offer the last one until the demo
has actually been run — the toolkit refuses it anyway, so a button for it would only be a
button that fails.

`content.py` supplies the differences between steps. Everything below the buttons is rebuilt
when a run finishes: a review page that did not exist when the page loaded is exactly the thing
the user is then supposed to open.
"""
from __future__ import annotations

from pathlib import Path

from nicegui import ui

from ...core import settings
from ...errors import ToolkitError
from .. import content, theme, topic_lists
from ..context import CONTEXT
from .common import (guard, info, inline_state, launch, run_status, section, shell,
                     terminal_viewer)
from .prompts import prompt_editor
from .regions import regions_editor
from .sample import BLURB as SAMPLE_BLURB
from .sample import needed_here, sample_section
from .settings_form import settings_form
from .spend import step_spend_box
from .topics_editor import editor
from .unsynced import unsynced_section

SET_QUERY = "set"

EXTRAS_BLURB = ("Nothing here is needed for a normal run. They rebuild review pages from results "
                "you already have, or show how the work will be divided up before any of it is "
                "sent.")


def href_for(step: content.Step) -> str:
    return f"/step/{step.slug}"


def step_page(slug: str, set: str | None = None,               # noqa: A002 - URL query name
              add: str | None = None) -> None:
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

        # The heading, and what this step has cost beside it — the same place on every step
        # page, at the top where the question is asked, not wherever the buttons happened to end.
        set_name = _chosen_set(step, set) if step.per_set else None
        _heading(step, set_name)
        if step.per_set:
            if _topic_lists(step, set_name, add) is None:
                return

        def refresh_all() -> None:
            actions.refresh()
            rest.refresh()

        @ui.refreshable
        def actions() -> None:
            _prerequisites(step)
            _sample(step, href, refresh_all)
            _flow(project, step, set_name, href, refresh_all)

        @ui.refreshable
        def rest() -> None:
            # The settings first: they change what the tagging produces. The rollup comes after,
            # because it reads what the tagging produced.
            _tuning(project, step, set_name, refresh_all)
            _sequels(project, step, set_name, href, refresh_all)
            if step.key == "summarize":
                unsynced_section(refresh_all)
            _extras(step, set_name, href)

        actions()
        rest()
        terminal_viewer()


def _chosen_set(step: content.Step, asked: str | None) -> str | None:
    """Which topic list this page is about, before anything is drawn — the heading needs it."""
    try:
        sets = CONTEXT.topic_sets()
    except ToolkitError:
        return None
    return asked if asked in sets else (sets[0] if sets else None)


def _heading(step: content.Step, set_name: str | None) -> None:
    with ui.row().classes("w-full items-start justify-between gap-4 flex-wrap mt-2"):
        with ui.column().classes("gap-0 grow min-w-64"):
            ui.label(step.title).classes("text-xl font-medium")
            ui.label(step.blurb).classes("text-sm opacity-70")
        if set_name or not step.per_set:
            step_spend_box(content.step_key(step, set_name))


def _fix(kind: str, step: content.Step, set_name: str | None, href: str) -> None:
    if kind == "sample":
        ui.timer(0, lambda: launch(content.SAMPLE.title, list(content.SAMPLE.argv), href),
                 once=True)
    else:
        ui.timer(0, lambda: _run_demo(step, set_name, href), once=True)


async def _run_demo(step: content.Step, set_name: str | None, href: str) -> None:
    await launch(content.job_title(step, content.DEMO_RUN, set_name),
                 content.run_argv(step, demo=True, set_name=set_name), href)


async def _run_full(step: content.Step, set_name: str | None, href: str) -> None:
    await launch(content.job_title(step, content.FULL_RUN, set_name),
                 content.run_argv(step, demo=False, set_name=set_name), href)


def _run_state(step: content.Step, set_name: str | None, href: str, kinds: tuple[str, ...],
               refresh) -> None:
    """The state of the runs this block starts, directly under its buttons."""
    run_status(titles={content.job_title(step, kind, set_name) for kind in kinds},
               on_fix=lambda kind: _fix(kind, step, set_name, href),
               on_finished=refresh, unit=step.unit)


ADD_QUERY = "add"

TABS_BLURB = ("Each list is tagged separately, with its own demo, its own prompt and its own "
              "settings — so a coarse list and a fine-grained one do not have to agree about "
              "anything.")


def _topic_lists(step: content.Step, chosen: str | None, add: str | None) -> str | None:
    """The list of topic lists, as tabs, and the way to add another.

    Returns the list being worked on, or None when the page has instead drawn the panel for
    making a new one — which is reachable whether or not there are lists already.
    """
    project = CONTEXT.require_project()
    try:
        sets = CONTEXT.topic_sets()
    except ToolkitError as e:
        guard(e)
        return None

    current = chosen if chosen in sets else (sets[0] if sets else None)
    if sets:
        _tabs(step, sets, None if add else current)
        ui.label(TABS_BLURB).classes("text-xs opacity-70 max-w-2xl")

    if sets and not add:
        return current

    with ui.card().classes("w-full"):
        ui.label("A new topic list" if sets else "No topic list yet.").classes("font-medium")
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


def _tabs(step: content.Step, sets: list[str], current: str | None) -> None:
    """One tab per topic list, each carrying how far that list has got, plus a tab that adds
    another. Drawn like the row of pages above it, because that is what it is."""
    from .. import stage

    status = _status()
    with ui.row().classes("w-full gap-1 flex-wrap items-center"):
        for name in sets:
            word, colour = stage.step_state(status, step, name)
            classes = "text-sm px-3 py-1 rounded no-underline flex items-center gap-2"
            classes += " bg-primary text-white" if name == current else " text-primary"
            with ui.link(target=f"{href_for(step)}?{SET_QUERY}={name}").classes(classes) \
                    .tooltip(f"{name}: {word}"):
                ui.label(name)
                ui.icon("circle", size="0.5rem").props(f"color={colour}")
        ui.link("+ Add a topic list", f"{href_for(step)}?{ADD_QUERY}=1") \
            .classes("text-sm px-3 py-1 rounded no-underline text-primary"
                     + (" bg-primary text-white" if current is None else ""))


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


def set_file(project, set_name: str):
    """The spreadsheet a topic list is kept in — the one it was uploaded as, or the one the app
    wrote when it was typed here."""
    from ...core.config import load_root_config

    entry = ((load_root_config(project).get("topics") or {}).get("sets") or {}).get(set_name) or {}
    if entry.get("file"):
        return project.root / entry["file"]
    discovered = topic_lists.discovered_path(project, set_name)
    return discovered or topic_lists.set_path(project, set_name)


def _edit_set(step: content.Step, project, set_name: str) -> None:
    """Change a list that is already in use, without leaving the app — whether it was written
    here or uploaded, and whichever format it is kept in."""
    path = set_file(project, set_name)
    with ui.expansion("The topic list itself", icon="list_alt").classes("w-full"):
        if not path.exists():
            ui.label(f"'{set_name}' should be kept in {path}, and that file is not there. "
                     f"Upload it again, or point config.yaml at where it now is.") \
                .classes("text-sm opacity-80")
            return
        ui.label("Changing a topic list changes what the tags mean, so the next full run will "
                 "ask you to try it out and review it again first.") \
            .classes("text-xs opacity-70 max-w-2xl")
        if path.suffix.lower() == ".xlsx":
            ui.label(f"{path.name} stays an Excel file. Saving rewrites the sheet the toolkit "
                     f"reads and leaves any other sheet in the workbook alone.") \
                .classes("text-xs opacity-60 max-w-2xl")
        editor(set_name, path,
               lambda _: ui.navigate.to(f"{href_for(step)}?{SET_QUERY}={set_name}"))


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
        with ui.card().classes(f"w-full {theme.WARN}"):
            ui.label("Import the transcripts first.").classes("text-sm font-medium")
            ui.link("Go to the workspace page", "/workspace").classes("text-sm")
        return
    missing = [n for n in step.needs if n not in have]
    if missing:
        with ui.card().classes(f"w-full {theme.WARN}"):
            ui.label(f"This step reads the {', '.join(missing)} from an earlier step. You can "
                     f"still run its demo — a demo of the previous step is enough for that.") \
                .classes("text-sm")


def _sample(step: content.Step, href: str, refresh) -> None:
    """Clip and label demos run on a fixed handful of interviews, chosen once. Offer the whole
    chooser here rather than letting the first demo fail for want of it — but the choice itself
    belongs to the project, so this is the workspace page's section, borrowed."""
    if not step.needs_sample or not needed_here(step):
        return
    with ui.card().classes(f"w-full {theme.NOTE}"):
        ui.label("You have not picked the demo interviews yet.").classes("text-sm font-medium")
        ui.label(SAMPLE_BLURB).classes("text-xs opacity-80 max-w-2xl")
        ui.link("They can also be changed on the workspace page.", "/workspace") \
            .classes("text-xs")
    sample_section(href, refresh)


# --- the three things a step page is for ---------------------------------------------------

DONE_DEMO = ("It has already run on these {unit}, and nothing that would change the answer has "
             "been edited since — the prompt, the model and this step's settings are all as they "
             "were. Running it again would send the same calls and get the same result back.\n\n"
             "Change something below and this comes back.")

DONE_FULL = ("It has already run on the whole collection, and nothing that would change the "
             "answer has been edited since — the prompt, the model and this step's settings are "
             "all as they were. Running it again would send nothing and cost nothing.\n\n"
             "To re-make the review pages from these results, use 'Rebuild these pages'. To get "
             "different results, change something below first.")

MORE_TO_DO = ("The last full run covered {covered} {unit}; there are {units} now. Running it "
              "again does the new ones only — the rest are already paid for.")


def _freshness(project, step: content.Step, set_name: str | None) -> dict:
    """Whether running this step again would produce anything new (steps/freshness.py)."""
    from ...steps.freshness import freshness

    try:
        return freshness(project, step.key, set_name)
    except (ToolkitError, OSError):
        return {"demo": "none", "full": "none"}


def _flow(project, step: content.Step, set_name: str | None, href: str, refresh) -> None:
    record = _status()["steps"].get(content.step_key(step, set_name), {})
    demo, full = record.get("demo"), record.get("full")
    fresh = _freshness(project, step, set_name)

    _try_it(step, set_name, href, demo, fresh, refresh)
    if not demo:
        return
    _read_it(project, step, set_name)
    _then(step, set_name, href, full, fresh, refresh)


def _run_again_button(label: str, step: content.Step, set_name: str | None, href: str, *,
                      full: bool, state: str, props: str) -> None:
    """A Run button that says so when pressing it would achieve nothing.

    The toolkit would happily re-run: every call is cached, so it would cost nothing and change
    nothing. But a button that looks live and then does nothing is the thing that makes people
    wonder whether it worked, so it is disabled and the reason is on it.
    """
    from ...steps import freshness as fresh_mod

    button = ui.button(label, icon="play_arrow" if full else "science",
                       on_click=(lambda: _run_full(step, set_name, href)) if full
                       else (lambda: _run_demo(step, set_name, href))).props(props)
    if state == fresh_mod.CURRENT:
        button.disable()
        button.tooltip((DONE_FULL if full else DONE_DEMO).format(unit=step.unit))
    elif state == fresh_mod.PARTIAL:
        button.tooltip("Some of this is already done — running it again does only what is new.")


def _try_it(step: content.Step, set_name: str | None, href: str, demo: dict | None,
            fresh: dict, refresh) -> None:
    """Step one, in its two states: the invitation to try it, and the record that it was tried.

    Only one button on the page runs a demo at a time — before there is one it is here, and after
    there is one it is at the bottom of the fork in step three, where the choice actually is.
    """
    with ui.card().classes("w-full"):
        if demo:
            ui.label("1 · The demo has run").classes("text-sm font-medium")
            units = len(demo.get("units") or ())
            ui.label(f"On {units} {step.unit} · {_when(demo['at'])}"
                     if units else _when(demo["at"])).classes("text-xs opacity-70")
            return
        ui.label("1 · Try it").classes("text-sm font-medium")
        ui.label(f"Runs on a few {step.unit} only and writes review pages. Nothing is saved to "
                 f"the project, and it costs a small fraction of the whole collection.") \
            .classes("text-xs opacity-70 max-w-2xl")
        _run_again_button("Run the demo", step, set_name, href, full=False,
                          state=fresh["demo"], props="dense color=primary")
    _run_state(step, set_name, href, (content.DEMO_RUN,), refresh)


def _rebuild_button(step: content.Step, set_name: str | None, href: str) -> None:
    """Re-render the review pages from results already saved. Free and instant, and the way to
    pick up an improvement to the pages themselves without paying for the step again."""
    annotate = next((a for a in step.extras if a.slug == "annotate"), None)
    if annotate is None or content.missing_for(annotate, _status()["deliverables"], set_name):
        return
    title = content.action_title(step, annotate, set_name)
    ui.button("Rebuild these pages", icon="refresh",
              on_click=lambda: launch(title, content.action_argv(annotate, set_name), href)) \
        .props("dense flat").tooltip("Writes them again from results you already have — no "
                                     "calls to OpenAI, nothing to pay for.")
    inline_state(title)


def _read_it(project, step: content.Step, set_name: str | None) -> None:
    pages = diag_pages(project, step, set_name)
    with ui.card().classes("w-full"):
        ui.label("2 · Read what came out").classes("text-sm font-medium")
        if step.review_hint:
            ui.label(step.review_hint).classes("text-xs opacity-70 max-w-2xl")
        if not pages:
            ui.label("The demo has not left a review page yet — the Terminal Viewer at the foot "
                     "of this page says what happened.").classes("text-sm opacity-70")
            return
        ui.label("This is the part to do before spending anything on the whole collection.") \
            .classes("text-xs opacity-60")
        with ui.row().classes("gap-3 flex-wrap items-center"):
            for i, (title, url) in enumerate(pages):
                ui.button(title, icon="open_in_new",
                          on_click=lambda _, u=url: ui.navigate.to(u, new_tab=True)) \
                    .props("dense" + (" color=primary" if i == 0 else " outline"))
            _rebuild_button(step, set_name, href_for(step))


def _then(step: content.Step, set_name: str | None, href: str, full: dict | None,
          fresh: dict, refresh) -> None:
    from ...steps import freshness as fresh_mod

    with ui.card().classes("w-full"):
        ui.label("3 · Then one of these").classes("text-sm font-medium")
        with ui.row().classes("w-full items-start gap-6 flex-wrap"):
            with ui.column().classes("gap-1 grow min-w-64"):
                ui.label("Not right yet?").classes("text-sm font-medium")
                ui.label("The prompt and the settings for this step are further down this page. "
                         "Change one, then try it again and read it again.") \
                    .classes("text-xs opacity-70 max-w-md")
                _run_again_button("Run the demo again", step, set_name, href, full=False,
                                  state=fresh["demo"], props="dense outline")
            with ui.column().classes("gap-1 grow min-w-64"):
                ui.label("Happy with it?").classes("text-sm font-medium")
                ui.label("Asks what it will cost and how to send the calls before spending "
                         "anything.").classes("text-xs opacity-70 max-w-md")
                if step.batch:
                    ui.label("It can go to OpenAI's Batch API at half price, taking up to a "
                             "day. You choose when it asks.").classes("text-xs opacity-60 max-w-md")
                _run_again_button("Run it on everything", step, set_name, href, full=True,
                                  state=fresh["full"], props="dense color=primary")
                if full:
                    ui.label(f"last full run {_when(full['at'])} · {full['model']} · "
                             f"{full['n_units']} {step.unit}").classes("text-xs opacity-60")
                if fresh["full"] == fresh_mod.PARTIAL:
                    ui.label("There is more in the collection now than that run covered.") \
                        .classes("text-xs tk-caution max-w-md")
    _run_state(step, set_name, href, (content.DEMO_RUN, content.FULL_RUN), refresh)


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


# --- the rest of the flow, and the tools around it ------------------------------------------

DONE_DERIVED = ("This has already run on what is there now, and nothing it reads has changed "
                "since — so it would write the same files again. Change a setting, or run the "
                "step it reads from, and this comes back.")


def _run_button(step: content.Step, action: content.Action, set_name: str | None, href: str,
                *, flat: bool = False, label: str = "Run", argv=None, done: bool = False) -> None:
    """A Run button that is only clickable when it would do something.

    Two ways it would not: what it reads is not there yet, or it has already run over exactly
    that and nothing has changed since. Both say so on the button rather than leaving it to be
    found out by pressing.
    """
    title = content.action_title(step, action, set_name)
    missing = content.missing_for(action, _status()["deliverables"], set_name)
    build = argv or (lambda: content.action_argv(action, set_name))
    button = ui.button(label, on_click=lambda _, t=title: launch(t, build(), href)) \
        .props("dense" + (" flat" if flat else ""))
    if missing:
        button.disable()
        button.tooltip(f"Nothing to work from yet — this reads the "
                       f"{', '.join(m.split(':')[0] for m in missing)} that "
                       f"'{step.title}' produces. Run this step first.")
    elif done:
        button.disable()
        button.tooltip(DONE_DERIVED)
    if flat:
        inline_state(title)


def _sequels(project, step: content.Step, set_name: str | None, href: str, refresh) -> None:
    """The moves that follow tagging in this branch of the pipeline, in the order they are made:
    see what each way of deciding would tag, then roll up with the one you picked. Numbered and
    in plain sight, because that order is the work — not a run with a decision hidden inside it."""
    if not step.sequels:
        return
    section("From clip tags to interview tags",
            "A clip is what the model reads; a catalogue entry is about an interview. These "
            "turn one into the other, and are worth running only once the whole collection "
            "has been tagged.")
    for i, action in enumerate(step.sequels, start=4):
        _sequel(project, step, set_name, href, i, action, refresh)


def _sequel(project, step: content.Step, set_name: str | None, href: str, number: int,
            action: content.Action, refresh) -> None:
    boxes: dict[str, object] = {}                # filled below, read when the button is pressed
    with ui.card().classes("w-full"):
        with ui.row().classes("items-start w-full gap-3"):
            with ui.column().classes("gap-1 grow"):
                with ui.row().classes("items-center gap-2"):
                    ui.label(f"{number} · {action.title}").classes("text-sm font-medium")
                    if action.explain:
                        info(action.explain)
                ui.label(action.blurb).classes("text-xs opacity-70 max-w-2xl")
                for title, url in _pages_of(project, step, action, set_name):
                    ui.button(title, icon="open_in_new",
                              on_click=lambda _, u=url: ui.navigate.to(u, new_tab=True)) \
                        .props("dense color=primary").classes("mt-1 self-start")
            if action.options == "compare":
                # Never disabled: comparing again with different variants is what it is for.
                _run_button(step, action, set_name, href, label="Compare",
                            argv=lambda: content.compare_argv(
                                action, set_name, {k: b.value for k, b in boxes.items()}))
            else:
                _run_button(step, action, set_name, href,
                            done=_already_done(project, step, action, set_name))
        if action.options == "compare":
            _compare_options(project, step, boxes)
        if action.setting == "rollup":
            _rollup_rule(step, set_name, refresh)
    _run_state_for(step, action, set_name, href, refresh)


def _already_done(project, step: content.Step, action: content.Action,
                  set_name: str | None) -> bool:
    """Whether this free, deterministic move has already been made over exactly what is there."""
    from ...steps import freshness as fresh_mod

    try:
        return fresh_mod.derived_state(project, step.key, action.slug, set_name) == \
            fresh_mod.CURRENT
    except (ToolkitError, OSError):
        return False


def _rollup_rule(step: content.Step, set_name: str | None, refresh) -> None:
    """The rule this rollup will use, inside the move that uses it.

    It is not among the step's settings: those change what the tagging produces, and this changes
    what is made of what it produced. Setting it and running it is one move, not two.
    """
    from ...core import settings as core_settings

    with ui.column().classes("w-full gap-1 mt-2 pt-2 tk-divide"):
        settings_form(step.key, [core_settings.rollup_field(step.key, set_name)],
                      on_saved=refresh, note=False, save_label="Save this rule")


def _run_state_for(step: content.Step, action: content.Action, set_name: str | None, href: str,
                   refresh) -> None:
    run_status(titles={content.action_title(step, action, set_name)}, on_finished=refresh)


def _pages_of(project, step: content.Step, action: content.Action,
              set_name: str | None) -> list[tuple[str, str]]:
    """Links to the pages this action has actually written — nothing before it has run."""
    base = project.diags_dir / step.key
    found = []
    for review in action.reviews:
        path = base / review.filename.format(set=set_name or "")
        if path.is_file():
            found.append((review.title,
                          "/diags/" + path.relative_to(project.diags_dir).as_posix()))
    return found


COMPARE_BLURB = ("What to draw. Leave these as they are unless the picture does not answer your "
                 "question — then change one and compare again.")


def _compare_options(project, step: content.Step, boxes: dict) -> None:
    """The variants the comparison draws, as boxes. Their contents start at whatever this
    project's advanced settings say, which is what the command would do on its own."""
    from ...core import thresholds
    from ...core.config import load_step_config

    try:
        current = thresholds.compare_text(
            thresholds.compare_options(load_step_config(project, step.key)))
    except ToolkitError as e:
        guard(e)
        return
    with ui.expansion("What to compare", icon="tune").classes("w-full mt-1"):
        ui.label(COMPARE_BLURB).classes("text-xs opacity-70 max-w-2xl")
        for key, _flag, label, hint in content.COMPARE_FIELDS:
            boxes[key] = ui.input(label, value=current.get(key, "")) \
                .props("dense outlined").classes("w-full")
            ui.label(hint).classes("text-xs opacity-60 max-w-2xl")


def _tuning(project, step: content.Step, set_name: str | None, refresh) -> None:
    """The things that change what this step produces, on the step's own page: what it is told to
    do, and the settings it runs with. For topics these belong to the chosen list, not to the
    step — two lists are two pieces of work."""
    per_list = bool(step.per_set and set_name)
    section(f"Change how '{set_name}' is tagged" if per_list else "Change how this step works")
    fields = settings.set_fields(set_name) if per_list else settings.for_step(step.key)
    with ui.expansion("Settings for this step", icon="tune").classes("w-full"):
        settings_form(step.key, fields, on_saved=refresh)
    with ui.expansion("The prompt for this step", icon="description").classes("w-full"):
        _prompt(project, step, set_name, refresh)
    if per_list:
        _edit_set(step, project, set_name)
    if step.key == "locations":
        # The list of regions is to locations what the topic list is to topics: the vocabulary
        # the tagging is done against, and the first thing to change when the tags are wrong.
        with ui.expansion("The regions the model may use", icon="public").classes("w-full"):
            regions_editor(on_saved=refresh)


def _prompt(project, step: content.Step, set_name: str | None, refresh) -> None:
    """A step's prompt, or a topic list's own if it has one.

    A topic list can carry its own rubric; until it does, the prompt shown is the one every list
    shares, and saying so is the difference between changing one list and changing them all.
    """
    from ...core import prompts as core_prompts

    if not (step.per_set and set_name):
        prompt_editor(step.key, set_name, on_saved=refresh)
        return

    shared = core_prompts.prompt_name(project, step.key) == \
        core_prompts.prompt_name(project, step.key, set_name)
    note = ("This prompt is shared by every topic list in this project — changing it changes "
            "them all. Give this list its own copy to change it on its own."
            if shared else "")
    prompt_editor(step.key, set_name, on_saved=refresh, shared_note=note)
    if shared:
        ui.button(f"Give '{set_name}' its own prompt", icon="call_split",
                  on_click=lambda: _split_prompt(project, step, set_name, refresh)) \
            .props("dense outline").classes("mt-2")


def _split_prompt(project, step: content.Step, set_name: str, refresh) -> None:
    """Copy the shared prompt to a file of this list's own and point the list at it."""
    from ...core import prompts as core_prompts
    from ...core import settings as core_settings

    name = f"tag_topics_{set_name}.md"
    destination = project.prompts_dir / name
    try:
        if not destination.exists():
            destination.write_text(core_prompts.prompt_path(project, step.key).read_text())
        core_settings.save(project, {f"topics.sets.{set_name}.prompt": name})
    except (ToolkitError, OSError) as e:
        guard(ToolkitError(f"Could not give '{set_name}' its own prompt: {e}"))
        return
    ui.notify(f"'{set_name}' now has its own prompt, prompts/{name}.", type="positive")
    refresh()


def _extras(step: content.Step, set_name: str | None, href: str) -> None:
    if not step.extras:
        return
    with ui.expansion("Extra tools", icon="build").classes("w-full mt-2"):
        ui.label(EXTRAS_BLURB).classes("text-xs opacity-70 max-w-2xl")
        for action in step.extras:
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
