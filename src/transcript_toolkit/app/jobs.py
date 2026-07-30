"""Running toolkit commands for the app.

Every command the app runs is the real `toolkit` CLI in a child process — the app never calls
a step function itself. That buys three things the GUI would otherwise have to reinvent:
Stop is a plain SIGINT (exactly Ctrl-C, which the CLI already recovers from because every step
is resumable), a crashing step cannot take the server down, and there is only ever one code
path to keep correct.

The child gets a pseudo-terminal rather than a pipe. Two reasons, both load-bearing:

1. **The confirmation prompt stays the CLI's.** A full run asks what it will cost and how to
   send the calls. Through a pty that question arrives verbatim — the app shows the CLI's own
   text and its own figures, and clicking a button types the answer back. No cost arithmetic
   is duplicated here, so the number a user approves cannot drift from the number the CLI
   computed.
2. Python line-buffers to a terminal and block-buffers to a pipe, so output appears as it
   happens instead of arriving in a lump when the step finishes.
"""
from __future__ import annotations

import asyncio
import codecs
import errno
import os
import pty
import signal
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from ..errors import ToolkitError
from . import content

# What a job actually runs. The module, not the `toolkit` shim, so a job always executes the
# same code as the server that spawned it — an app updated mid-session cannot end up driving
# an older CLI. Tests point this at a stub child.
CHILD_COMMAND = [sys.executable, "-m", "transcript_toolkit.cli"]

MAX_LOG_LINES = 5000            # a corpus run prints a few thousand lines; keep the tail
DRAIN_AFTER_EXIT_S = 5.0        # bounded wait for the last output after the child exits
SIGKILL_AFTER_S = 120.0         # longer than any single call can take, so Ctrl-C gets its chance
UNKNOWN_PROMPT_AFTER_S = 3.0    # an unfinished line this old, with nothing else arriving, is a question

RUNNING, WAITING, SUCCEEDED = "running", "waiting", "succeeded"
FAILED, STOPPED, CANCELLED = "failed", "stopped", "cancelled"
LIVE_STATES = (RUNNING, WAITING)


@dataclass
class Job:
    """One command, its output, and what it is waiting for."""
    id: int
    title: str                          # "Label — full run"
    command: str                        # "toolkit label", as the user would type it
    workspace: Path
    started_at: float
    href: str = "/"                     # the page that shows this run
    state: str = RUNNING
    returncode: int | None = None
    ended_at: float | None = None
    lines: deque[str] = field(default_factory=lambda: deque(maxlen=MAX_LOG_LINES))
    prompt: str = ""                    # the question the command is blocked on, if any
    error: str = ""                     # the CLI's own error text, when it failed
    revision: int = 0                   # bumped on every change, so a page knows to redraw
    emitted: int = 0                    # lines ever written, including ones aged out of `lines`
    pending: str = ""                   # output with no newline yet — usually a question
    pending_at: float = 0.0             # when that unfinished line last changed

    def add_line(self, line: str) -> None:
        self.lines.append(line)
        self.emitted += 1

    def since(self, seen: int) -> list[str]:
        """Lines written since the caller last looked.

        Counted from `emitted` rather than from the buffer's length, because a long run drops
        its oldest lines. Nothing new means nothing to send: a page redraws for reasons that
        add no output (a question arriving, the run ending), and returning the buffer then
        would print the whole run again underneath itself.
        """
        missed = self.emitted - max(seen, 0)
        if missed <= 0:
            return []
        return list(self.lines)[-missed:] if missed <= len(self.lines) else list(self.lines)

    @property
    def live(self) -> bool:
        return self.state in LIVE_STATES

    @property
    def duration(self) -> float:
        return (self.ended_at or time.time()) - self.started_at

    def text(self) -> str:
        return "\n".join(self.lines)

    def answers(self) -> tuple[content.Answer, ...] | None:
        """Buttons for the prompt it is blocked on (None when not blocked or unrecognised)."""
        return content.answers_for(self.prompt) if self.state == WAITING else None

    def unanswered_question(self) -> str:
        """An unfinished line that has sat still while nothing else arrived — something is
        waiting for an answer the app has no button for. Rendering it (with a plain text box)
        is the difference between a strange question and a silent hang."""
        if not self.live or self.state == WAITING or not self.pending:
            return ""
        return self.pending if time.time() - self.pending_at > UNKNOWN_PROMPT_AFTER_S else ""


class JobManager:
    """One job at a time, server-side, so a job outlives the browser tab that started it.

    Single-slot on purpose: the pipeline is a sequence, and a second run of the same step
    while the first is live would duplicate spend. A Batch API run can hold the slot for
    hours — stopping it is safe and the UI says so, because the batch keeps processing at
    OpenAI and re-running the step re-attaches to it.
    """

    def __init__(self) -> None:
        self.current: Job | None = None
        self._next_id = 1
        self._proc: asyncio.subprocess.Process | None = None
        self._master_fd: int | None = None
        self._decoder = None            # one decoder per job: characters can straddle reads
        self._eof = asyncio.Event()
        self._killer: asyncio.Task | None = None

    @property
    def busy(self) -> bool:
        return self.current is not None and self.current.live

    def forget(self) -> None:
        """Drop the finished job, so nothing is left on screen from it.

        Used when the open workspace changes: output from the project you just closed, sitting
        under the project you just opened, reads as if it belonged to the new one.
        """
        if self.busy:
            raise ToolkitError(f"'{self.current.title}' is still running.")
        self.current = None

    # --- starting -------------------------------------------------------------------------
    async def start(self, title: str, argv: list[str], workspace: Path,
                    href: str = "/", with_project: bool = True) -> Job:
        if self.busy:
            raise ToolkitError(
                f"'{self.current.title}' is still running. Wait for it to finish, or stop it "
                f"first — finished calls are cached either way.")

        job = Job(id=self._next_id, title=title, command=content.display_command(argv),
                  workspace=workspace, started_at=time.time(), href=href)
        self._next_id += 1
        self.current = job
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._eof = asyncio.Event()

        full_argv = [*argv, "--project", str(workspace)] if with_project else list(argv)
        master_fd, slave_fd = pty.openpty()
        try:
            proc = await asyncio.create_subprocess_exec(
                *CHILD_COMMAND, *full_argv,
                stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
                cwd=str(workspace), env=self._child_env(),
            )
        except OSError as e:
            # Nothing was spawned, so nothing will ever finish this job. Clearing it matters:
            # a job left in `running` would make the app refuse every later run as "still
            # running" and refuse to quit, with no way out but killing the server from a
            # terminal. The real trigger is a project folder renamed or moved in Finder.
            os.close(master_fd)
            self.current = None
            raise ToolkitError(
                f"Could not start {content.display_command(argv)}: {e}\n"
                f"If the project folder was moved or renamed, open it again on the Workspace "
                f"page.") from e
        finally:
            os.close(slave_fd)          # the child holds the only copy now; we read the master

        self._proc, self._master_fd = proc, master_fd
        os.set_blocking(master_fd, False)
        asyncio.get_running_loop().add_reader(master_fd, self._on_readable)
        asyncio.create_task(self._supervise(job, proc))
        return job

    @staticmethod
    def _child_env() -> dict[str, str]:
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        env["TOOLKIT_NO_OPEN"] = "1"            # the app links the review pages itself
        env["TOOLKIT_NO_UPDATE_CHECK"] = "1"    # Settings does the update check, once
        return env

    # --- reading --------------------------------------------------------------------------
    def _on_readable(self) -> None:
        fd = self._master_fd
        if fd is None:
            return
        try:
            data = os.read(fd, 65536)
        except BlockingIOError:
            return
        except OSError as e:
            if e.errno != errno.EIO:    # EIO is how a pty says the child let go; nothing else is
                raise
            data = b""
        if not data:
            self._close_reader()
            self._eof.set()
            return
        self._absorb(self._decoder.decode(data))

    def _absorb(self, text: str) -> None:
        job = self.current
        if job is None:
            return
        # A terminal writes \r\n; normalise after appending, so a boundary falling between the
        # two does not leave a stray blank line.
        pending = (job.pending + text).replace("\r\n", "\n").replace("\r", "\n")
        *complete, pending = pending.split("\n")
        for line in complete:
            job.add_line(line)
        if pending != job.pending:
            job.pending, job.pending_at = pending, time.time()

        # `input()` writes its prompt without a newline, so an unfinished tail is either a
        # question or output still arriving. Only a recognised question changes the state;
        # an unrecognised one surfaces later through `Job.unanswered_question`.
        if job.state in LIVE_STATES:
            if content.answers_for(pending):
                job.state, job.prompt = WAITING, pending
            elif job.state == WAITING:
                job.state, job.prompt = RUNNING, ""
        job.revision += 1

    def _close_reader(self) -> None:
        if self._master_fd is None:
            return
        asyncio.get_running_loop().remove_reader(self._master_fd)
        os.close(self._master_fd)
        self._master_fd = None

    # --- finishing ------------------------------------------------------------------------
    async def _supervise(self, job: Job, proc: asyncio.subprocess.Process) -> None:
        returncode = await proc.wait()
        try:                                    # let the last lines arrive, but never hang
            await asyncio.wait_for(self._eof.wait(), timeout=DRAIN_AFTER_EXIT_S)
        except asyncio.TimeoutError:
            pass
        self._close_reader()
        if job.pending:
            job.add_line(job.pending)
            job.pending = ""

        if self._killer is not None:
            self._killer.cancel()
            self._killer = None

        job.returncode = returncode
        job.ended_at = time.time()
        job.prompt = ""
        job.state = _classify(returncode)
        if job.state == FAILED:
            job.error = _error_text(job.lines)
            if content.is_cancellation(job.error):
                # Declining to spend money is a decision, not a fault, even though the CLI
                # reports it the same way it reports a problem.
                job.state, job.error = CANCELLED, ""
        job.revision += 1
        self._proc = None

        if job.state == SUCCEEDED and job.title == content.UPDATE_TITLE \
                and content.updated_version(job.lines):
            # The code this server is running has just been replaced on disk. Nothing here will
            # be the new version until it starts again, so it does.
            from . import server
            server.ask_restart()

    # --- talking back ---------------------------------------------------------------------
    def answer(self, text: str) -> None:
        """Type a line into the running command — the answer to what it asked.

        Only while it is actually waiting: the panel redraws on a timer, so the buttons stay
        clickable for a moment after the first click, and a second answer would sit in the
        terminal's buffer and silently pre-answer the next question.
        """
        job = self.current
        if self._master_fd is None or job is None or not job.live or not job.pending:
            raise ToolkitError("That command is no longer waiting for an answer.")
        job.state, job.prompt, job.pending = RUNNING, "", ""
        job.revision += 1
        try:
            os.write(self._master_fd, (text + "\n").encode())
        except OSError as e:
            raise ToolkitError("That command is no longer waiting for an answer.") from e

    async def stop(self) -> None:
        """Ctrl-C the running command. Safe by design: every step caches each finished call,
        so re-running it later continues from where it stopped."""
        proc, job = self._proc, self.current
        if proc is None or job is None or not job.live:
            raise ToolkitError("Nothing is running.")
        job.add_line("")
        job.add_line("--- stopping (Ctrl-C) ---")
        job.revision += 1
        proc.send_signal(signal.SIGINT)
        self._killer = asyncio.create_task(self._kill_if_stuck(proc, job))

    async def _kill_if_stuck(self, proc: asyncio.subprocess.Process, job: Job) -> None:
        """A last resort. A step finishes the call it is in the middle of before it can act on
        Ctrl-C, so the wait has to be longer than one call can take."""
        await asyncio.sleep(SIGKILL_AFTER_S)
        if proc.returncode is None:
            job.add_line(f"--- still going {SIGKILL_AFTER_S:.0f}s after Ctrl-C; closing it down "
                         f"(finished calls are still saved) ---")
            job.revision += 1
            proc.kill()


def _classify(returncode: int) -> str:
    if returncode == 0:
        return SUCCEEDED
    if returncode in (130, -signal.SIGINT, -signal.SIGKILL):
        return STOPPED
    return FAILED


def _error_text(lines: deque[str]) -> str:
    """The CLI's own message. It prints `error: <what went wrong and how to fix it>` and
    exits 2; anything after that line belongs to the same message."""
    out: list[str] = []
    for line in lines:
        if line.startswith("error: "):
            out = [line[len("error: "):]]
        elif out:
            out.append(line)
    return "\n".join(out).strip()
