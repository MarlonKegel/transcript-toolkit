"""The page shell, the status panel and the terminal viewer — what every page is built out of."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Callable

from nicegui import ui

from ... import __version__
from ...core.config import project_name
from ...errors import ToolkitError
from .. import content, jobs, theme
from ..context import CONTEXT

# Home is not in here: it is the list of projects, and you get to it from the icon in the
# corner. Settings is not in here either — it is the same on every page and belongs behind the
# gear, not in the row of places you go in order.
NAV = [("/workspace", "Workspace"),
       *[(f"/step/{s.slug}", s.title) for s in content.STEPS],
       ("/export", "Export")]

STATE_LOOK = {
    jobs.RUNNING: ("play_circle", "text-primary", "running"),
    jobs.WAITING: ("help", "tk-caution", "waiting for you"),
    jobs.SUCCEEDED: ("check_circle", "tk-good", "finished"),
    jobs.FAILED: ("error", "tk-bad", "failed"),
    jobs.STOPPED: ("stop_circle", "opacity-60", "stopped"),
    jobs.CANCELLED: ("do_not_disturb_on", "opacity-60", "cancelled"),
}

ICON_URL = "/app-icon.png"


def shown_name(project) -> str:
    """The project's name, for the header — which is drawn on every page including the one you
    would go to in order to fix a config.yaml you have broken. So a config that will not parse
    falls back to the folder name instead of blanking the app."""
    try:
        return project_name(project)
    except ToolkitError:
        return project.root.name


def guard(e: Exception) -> None:
    """Show a failure the way the toolkit does: its own words, no traceback."""
    ui.notify(str(e), type="negative", multi_line=True, close_button="OK",
              classes="max-w-xl whitespace-pre-line")


@contextmanager
def shell(active: str = "", *, needs_workspace: bool = True, settings_open: bool = False):
    """Header, navigation, the settings drawer, and the centred column pages draw into."""
    theme.apply()
    # Before anything reads a file out of it: the folder may have been renamed or thrown away
    # in Finder since the page was last drawn.
    CONTEXT.check_still_there()
    project = CONTEXT.project
    if needs_workspace and project is None:
        ui.navigate.to("/")

    drawer = _settings_drawer(active, settings_open)

    with ui.header().classes("items-center px-4 py-2 gap-2"):
        with ui.row().classes("items-center gap-2 flex-1 min-w-0"):
            with ui.link(target="/").classes("no-underline flex items-center gap-2") \
                    .tooltip("All your projects"):
                ui.image(ICON_URL).classes("w-7 h-7 rounded")
                ui.label("Transcript Toolkit").classes("text-lg font-medium text-white")
                # In plain sight because the first question about any odd behaviour is which
                # version is running, and the answer must not require opening a terminal.
                ui.label(__version__).classes("text-xs opacity-60 text-white")
        centre = ui.row().classes("items-center gap-2 justify-center flex-1 min-w-0")
        if project is not None:
            with centre:
                ui.icon("folder_open", size="1.1rem")
                ui.label(shown_name(project)).classes("text-sm font-medium truncate")
        with ui.row().classes("items-center justify-end flex-1"):
            ui.button(icon="settings", on_click=drawer.toggle) \
                .props("flat round dense color=white").tooltip("Settings")

    with ui.row().classes("w-full max-w-5xl mx-auto px-4 pt-4 gap-1 flex-wrap"):
        for href, title in NAV:
            classes = "text-sm px-3 py-1 rounded no-underline"
            classes += " bg-primary text-white" if href == active else " text-primary"
            ui.link(title, href).classes(classes)

    with ui.column().classes("w-full max-w-5xl mx-auto p-4 gap-4") as body:
        _running_banner(active)
        yield body


def _settings_drawer(active: str, opened: bool):
    """Settings, on every page, behind the gear. It is about the installation and the open
    project rather than a place in the pipeline, so it does not belong in the row above."""
    from .settings import settings_body

    drawer = ui.right_drawer(value=opened, bordered=True).props("width=460 overlay")
    with drawer:
        with ui.row().classes("items-center w-full"):
            ui.label("Settings").classes("text-lg font-medium")
            ui.space()
            ui.button(icon="close", on_click=drawer.hide).props("flat round dense")
        on_open = settings_body(active)

    # Only when it is actually opened, and only the first time: the version check calls out to
    # GitHub, and this drawer is built on every page.
    done = {"checked": False}

    async def opened_now(event=None) -> None:
        if done["checked"] or (event is not None and not event.value):
            return
        done["checked"] = True
        await on_open()

    drawer.on_value_change(opened_now)
    if opened:
        ui.timer(0.1, opened_now, once=True)
    return drawer


def _running_banner(active: str) -> None:
    """On every page: what is running, if anything, and where to watch it."""
    holder = ui.row().classes("w-full")

    def tick() -> None:
        job = CONTEXT.jobs.current
        show = job is not None and job.live and job.href != active
        holder.clear()
        holder.set_visibility(bool(show))
        if not show:
            return
        with holder:
            with ui.card().classes(f"w-full {theme.NOTE} py-2"):
                with ui.row().classes("items-center gap-3"):
                    ui.spinner(size="1.2rem")
                    ui.label(f"{job.title} is {STATE_LOOK[job.state][2]}").classes("text-sm")
                    ui.link("watch it", job.href).classes("text-sm")

    ui.timer(1.0, tick)


def info(text: str) -> None:
    """A small `i` that explains something on hover, for the things a first-time user will
    wonder about but a regular one should not have to read every time."""
    with ui.icon("info").classes("opacity-50 cursor-help").props("size=1rem"):
        ui.tooltip(text).classes("max-w-sm text-xs whitespace-pre-line")


def section(title: str, blurb: str = "") -> None:
    ui.label(title).classes("text-xl font-medium mt-2")
    if blurb:
        ui.label(blurb).classes("text-sm opacity-70 -mt-1")


def status_chip(text: str, colour: str) -> None:
    ui.chip(text, color=colour, text_color="white").props("dense square").classes("text-xs")


# --- the run status panel ------------------------------------------------------------------

def run_status(on_fix: Callable[[str], None] | None = None,
               on_finished: Callable[[], None] | None = None, unit: str = "") -> None:
    """What the command that was just started is doing, drawn where it was started from.

    It reads the job off the server, so it is the same panel whether the run started a second
    ago in this tab or an hour ago in a tab that has since been closed. Its output is not here:
    that is the Terminal Viewer at the foot of the page.
    """
    seen = {"id": None, "revision": -1, "finished": None}

    with ui.card().classes("w-full") as card:
        header = ui.row().classes("items-center gap-2 w-full")
        progress_area = ui.column().classes("w-full gap-1")
        prompt_area = ui.column().classes("w-full gap-2")
        error_area = ui.column().classes("w-full gap-2")

    def redraw(job: jobs.Job) -> None:
        icon, colour, word = STATE_LOOK[job.state]
        header.clear()
        with header:
            ui.icon(icon).classes(colour)
            ui.label(f"{job.title} — {word}").classes("font-medium")
            ui.space()
            ui.label(f"{job.duration:.0f}s").classes("text-xs opacity-60")
            if job.live:
                ui.button("Stop", icon="stop", on_click=_stop, color="negative") \
                    .props("outline dense").tooltip(
                        "Safe to stop: every finished call is saved, so running this again "
                        "carries on from where it stopped.")

        progress_area.clear()
        if job.live:
            with progress_area:
                _progress(job, unit)

        prompt_area.clear()
        if job.state == jobs.WAITING:
            with prompt_area, ui.card().classes(f"w-full {theme.WARN}"):
                ui.label("The toolkit is asking before it spends anything:") \
                    .classes("text-xs opacity-70")
                # Its own words and its own figures, lifted from the run itself, so nothing
                # here is a second opinion about what something costs.
                ui.label(_question_block(job)).classes("whitespace-pre-line font-mono text-sm")
                with ui.row().classes("gap-2 flex-wrap"):
                    for answer in job.answers() or ():
                        ui.button(answer.label,
                                  on_click=lambda _, a=answer: _answer(a.send)) \
                            .props(f"color={answer.tone or 'primary'} dense")
        elif job.unanswered_question():
            with prompt_area, ui.card().classes(f"w-full {theme.WARN}"):
                ui.label("It is waiting for an answer:").classes("text-xs opacity-70")
                ui.label(job.unanswered_question()).classes("font-mono text-sm")
                reply = ui.input("Type your answer").classes("w-full")
                ui.button("Send", on_click=lambda: _answer(reply.value)).props("dense")

        error_area.clear()
        if job.state == jobs.FAILED and job.error:
            with error_area, ui.card().classes(f"w-full {theme.FAIL}"):
                ui.label("It stopped with this:").classes("text-xs opacity-70")
                ui.label(job.error).classes("whitespace-pre-line text-sm")
                fix = content.fix_for(job.error)
                if fix and on_fix:
                    label = "Pick the demo interviews" if fix == "sample" else "Run the demo"
                    ui.button(label, icon="play_arrow",
                              on_click=lambda _, f=fix: on_fix(f)).props("dense")
        elif job.state == jobs.FAILED:
            # No message means the toolkit did not stop of its own accord. Give the user the
            # tail of the log and a way to send it on, rather than a red box with nothing in it.
            with error_area, ui.card().classes(f"w-full {theme.FAIL}"):
                ui.label("It stopped unexpectedly. These are its last lines — send them to "
                         "whoever looks after the toolkit.").classes("text-sm")
                tail = "\n".join(list(job.lines)[-20:])
                ui.label(tail).classes("whitespace-pre-line font-mono text-xs opacity-80")
                ui.button("Copy them", icon="content_copy",
                          on_click=lambda: _copy(job)).props("dense flat")
        elif job.state == jobs.CANCELLED:
            with error_area:
                ui.label("Cancelled — nothing was spent.").classes("text-sm opacity-80")
        elif job.state == jobs.STOPPED:
            with error_area:
                ui.label("Stopped. Every call that finished is saved — running this again "
                         "picks up where it left off.").classes("text-sm opacity-80")

    def tick() -> None:
        job = CONTEXT.jobs.current
        card.set_visibility(job is not None)
        if job is None:
            return
        if seen["id"] != job.id:
            seen.update(id=job.id, revision=-1)
        if job.revision != seen["revision"] or job.live or job.unanswered_question():
            seen["revision"] = job.revision
            redraw(job)
        if not job.live and seen["finished"] != job.id:
            seen["finished"] = job.id
            if on_finished:                     # the page's own sections are now out of date
                on_finished()

    async def _stop() -> None:
        try:
            await CONTEXT.jobs.stop()
        except ToolkitError as e:
            guard(e)

    def _answer(text: str) -> None:
        try:
            CONTEXT.jobs.answer(text)
        except ToolkitError as e:
            guard(e)

    def _copy(job: jobs.Job) -> None:
        ui.clipboard.write("\n".join(list(job.lines)[-200:]))
        ui.notify("Copied to the clipboard.", type="positive")

    card.set_visibility(False)
    ui.timer(0.4, tick)


def _progress(job: jobs.Job, unit: str) -> None:
    """How far the run has got. Every step counts off the work it does, so this is the run's own
    count read back — not an estimate made here."""
    counted = content.progress_of(job.lines)
    if counted:
        done, total = counted
        ui.linear_progress(value=done / total, show_value=False, size="10px") \
            .props("rounded color=primary")
        ui.label(f"{done} of {total} {unit or 'done'}".rstrip()).classes("text-xs opacity-70")
    else:
        with ui.row().classes("items-center gap-2"):
            ui.spinner(size="1rem")
            ui.label("Starting…").classes("text-xs opacity-70")
    latest = _latest(job)
    if latest:
        ui.label(latest).classes("text-xs opacity-60 font-mono truncate w-full")


def inline_state(title: str) -> None:
    """A one-line live state for a Run button further down a page, so a click there is visibly
    answered without scrolling to the panel at the top."""
    holder = ui.row().classes("items-center gap-2")

    def tick() -> None:
        job = CONTEXT.jobs.current
        show = job is not None and job.title == title
        holder.clear()
        holder.set_visibility(bool(show))
        if not show:
            return
        icon, colour, word = STATE_LOOK[job.state]
        with holder:
            ui.icon(icon).classes(colour).props("size=1rem")
            ui.label(f"{word} · {job.duration:.0f}s").classes("text-xs opacity-70")

    holder.set_visibility(False)
    ui.timer(0.5, tick)


# --- the terminal viewer -------------------------------------------------------------------

TERMINAL_EXPLAINER = (
    "This app is a window onto a command-line tool. Everything you click here runs the same "
    "`toolkit` command a person would type in Terminal, on this Mac — nothing is sent anywhere "
    "except the calls to OpenAI.\n\n"
    "What you see below is that command's own output, exactly as Terminal would show it: the "
    "line at the top is the command being run, and the dark panel is what it printed.\n\n"
    "You never have to read this. It is here so you can see what is happening, and so you can "
    "copy a command out and run it yourself if you ever want to."
)


def explainer() -> None:
    info(TERMINAL_EXPLAINER)


def terminal_viewer() -> None:
    """The last section of every page that can run something: the command, and its output as it
    appears. Separate from the status panel, which sits next to the button that started it."""
    seen = {"id": None, "lines": 0}

    with ui.row().classes("items-center gap-2 mt-4"):
        ui.label("Terminal Viewer").classes("text-xl font-medium")
        explainer()
    ui.label("What the toolkit is doing on your Mac, as it does it.").classes("text-sm opacity-70")
    with ui.card().classes("w-full"):
        idle = ui.label("Nothing has run yet in this project.").classes("text-sm opacity-60")
        command = ui.code("", language="bash").classes("w-full text-xs")
        log = ui.log(max_lines=jobs.MAX_LOG_LINES).classes(
            "w-full h-72 text-xs font-mono rounded p-2 tk-terminal")

    def tick() -> None:
        job = CONTEXT.jobs.current
        idle.set_visibility(job is None)
        command.set_visibility(job is not None)
        log.set_visibility(job is not None)
        if job is None:
            return
        if seen["id"] != job.id:
            log.clear()
            seen.update(id=job.id, lines=0)
            command.content = f"$ {job.command}"
        for line in job.since(seen["lines"]):
            log.push(line)
        seen["lines"] = job.emitted

    tick()
    ui.timer(0.4, tick)


def _latest(job: jobs.Job) -> str:
    """The last thing the command said — a sign of life while it is still going."""
    for line in reversed(list(job.lines)):
        if line.strip():
            return line.strip()
    return ""


def _question_block(job: jobs.Job) -> str:
    """The command's own question: everything it printed since the last blank line, and the
    unfinished prompt line itself."""
    block = [job.prompt.strip()] if job.prompt.strip() else []
    for line in reversed(list(job.lines)):
        if not line.strip():
            break
        block.append(line)
    return "\n".join(reversed(block))


async def launch(title: str, argv: list[str], href: str = "/") -> None:
    """Start a command in the open workspace, or say why not."""
    try:
        await CONTEXT.jobs.start(title, argv, CONTEXT.require_project().root, href=href)
    except ToolkitError as e:
        guard(e)


async def launch_global(title: str, argv: list[str], href: str = "/") -> None:
    """Start a command that is about the installation, not about one project."""
    from pathlib import Path
    try:
        await CONTEXT.jobs.start(title, argv, Path.home(), href=href, with_project=False)
    except ToolkitError as e:
        guard(e)
