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
MAX_HISTORY = 10
DRAIN_AFTER_EXIT_S = 5.0        # bounded wait for the last output after the child exits
SIGKILL_AFTER_S = 30.0          # a step that ignores SIGINT for this long is stuck

RUNNING, WAITING, SUCCEEDED, FAILED, STOPPED = "running", "waiting", "succeeded", "failed", "stopped"
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

    def add_line(self, line: str) -> None:
        self.lines.append(line)
        self.emitted += 1

    def since(self, seen: int) -> list[str]:
        """Lines written after the caller last looked. A long run drops its oldest lines, so
        pages count from `emitted`, not from the length of the buffer."""
        missed = self.emitted - max(seen, 0)
        return list(self.lines)[-missed:] if 0 < missed <= len(self.lines) else list(self.lines)

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


class JobManager:
    """One job at a time, server-side, so a job outlives the browser tab that started it.

    Single-slot on purpose: the pipeline is a sequence, and a second run of the same step
    while the first is live would duplicate spend. A Batch API run can hold the slot for
    hours — stopping it is safe and the UI says so, because the batch keeps processing at
    OpenAI and re-running the step re-attaches to it.
    """

    def __init__(self) -> None:
        self.current: Job | None = None
        self.history: deque[Job] = deque(maxlen=MAX_HISTORY)
        self._next_id = 1
        self._proc: asyncio.subprocess.Process | None = None
        self._master_fd: int | None = None
        self._pending = ""              # output not yet terminated by a newline: the prompt
        self._eof = asyncio.Event()
        self._killer: asyncio.Task | None = None

    @property
    def busy(self) -> bool:
        return self.current is not None and self.current.live

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
        self.history.appendleft(job)
        self._pending = ""
        self._eof = asyncio.Event()

        full_argv = [*argv, "--project", str(workspace)] if with_project else list(argv)
        master_fd, slave_fd = pty.openpty()
        try:
            proc = await asyncio.create_subprocess_exec(
                *CHILD_COMMAND, *full_argv,
                stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
                cwd=str(workspace), env=self._child_env(),
            )
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
        except OSError:
            data = b""      # EIO: on Linux this is how a pty reports that the child let go
        if not data:
            self._close_reader()
            self._eof.set()
            return
        self._absorb(data.decode("utf-8", "replace"))

    def _absorb(self, text: str) -> None:
        job = self.current
        if job is None:
            return
        # A terminal ends lines with \r\n, and a step's progress counter may rewrite one line
        # with a bare \r. Both become plain lines here.
        self._pending += text.replace("\r\n", "\n").replace("\r", "\n")
        *complete, self._pending = self._pending.split("\n")
        for line in complete:
            job.add_line(line)

        # `input()` writes its prompt without a newline, so an unterminated tail is either a
        # question or output still arriving. Only a recognised question changes the state.
        if job.state in LIVE_STATES:
            if content.answers_for(self._pending):
                job.state, job.prompt = WAITING, self._pending
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
        if self._pending:
            job.add_line(self._pending)
            self._pending = ""

        if self._killer is not None:
            self._killer.cancel()
            self._killer = None

        job.returncode = returncode
        job.ended_at = time.time()
        job.prompt = ""
        job.state = _classify(returncode)
        if job.state == FAILED:
            job.error = _error_text(job.lines)
        job.revision += 1
        self._proc = None

    # --- talking back ---------------------------------------------------------------------
    def answer(self, text: str) -> None:
        """Type a line into the running command (the answer to its prompt)."""
        if self._master_fd is None or self.current is None or not self.current.live:
            raise ToolkitError("That command is no longer waiting for an answer.")
        os.write(self._master_fd, (text + "\n").encode())
        self.current.state, self.current.prompt = RUNNING, ""
        self.current.revision += 1

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
        await asyncio.sleep(SIGKILL_AFTER_S)
        if proc.returncode is None:
            job.add_line(f"--- no response after {SIGKILL_AFTER_S:.0f}s, forcing it to quit ---")
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
