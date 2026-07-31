"""The app starting itself again after an update.

Updating replaces the code this server is running, so nothing in the window is the new version
until the server starts again. It does that by replacing its own process image once the event
loop has stopped — the risky part, and the part worth testing for real: the port has to be let
go and taken again, and the process has to survive it.
"""
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from transcript_toolkit.app import server

PROBE = Path(__file__).parent / "restart_probe.py"
START_TIMEOUT_S = 60.0


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def health(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as r:
            return r.status == 200
    except (OSError, urllib.error.HTTPError):
        return False


def wait_for(check, timeout: float = START_TIMEOUT_S) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if check():
            return True
        time.sleep(0.25)
    return False


def cmdline(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().decode("utf-8", "replace")
    except OSError:
        return ""


@pytest.mark.skipif(not Path("/proc").is_dir(), reason="reads /proc to see the process change")
def test_the_app_replaces_itself_and_takes_the_port_back(tmp_path):
    port = free_port()
    env = dict(os.environ)
    env.pop("PYTEST_CURRENT_TEST", None)
    env["HOME"] = str(tmp_path)
    env["XDG_CONFIG_HOME"] = str(tmp_path / ".config")
    (tmp_path / ".config").mkdir(parents=True, exist_ok=True)

    process = subprocess.Popen([sys.executable, str(PROBE), str(tmp_path / "asked"), str(port)],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                               env=env)
    try:
        assert wait_for(lambda: health(port)), "the app never came up"
        before = cmdline(process.pid)
        assert "restart_probe.py" in before

        # ask_restart fires a second in; the server stops and starts again on the real command
        assert wait_for(lambda: "restart_probe.py" not in cmdline(process.pid) and
                        cmdline(process.pid) != ""), "the process image never changed"
        assert "transcript_toolkit.cli" in cmdline(process.pid)
        assert process.poll() is None, "it exited instead of starting again"
        assert wait_for(lambda: health(port)), "it never took the port back"
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def test_it_starts_again_from_a_path_the_upgrade_does_not_move(monkeypatch, tmp_path):
    """`sys.executable` lives inside the tool environment uv rebuilds; the `toolkit` in uv's bin
    directory is what the desktop launcher runs and what uv keeps pointing at the new code."""
    from transcript_toolkit.app.context import CONTEXT

    monkeypatch.setattr(CONTEXT, "project", None)

    launcher = tmp_path / "toolkit"
    launcher.write_text("#!/bin/sh\n")
    monkeypatch.setattr(sys, "argv", [str(launcher)])
    assert server.restart_argv(8377)[0] == str(launcher)
    assert server.restart_argv(8377)[1:] == ["app", "--port", "8377", "--no-browser"]

    monkeypatch.setattr(sys, "argv", [str(tmp_path / "pytest")])     # not the toolkit command
    assert server.restart_argv(8377)[:3] == [sys.executable, "-m", "transcript_toolkit.cli"]


def test_a_restart_is_asked_for_only_once(monkeypatch):
    monkeypatch.setitem(server.RESTART, "asked", False)
    asked = []
    monkeypatch.setattr(server, "RESTART_DELAY_S", 0)

    class FakeLoop:
        @staticmethod
        def create_task(coro):
            coro.close()
            asked.append(1)

    monkeypatch.setattr("asyncio.create_task", FakeLoop.create_task)
    server.ask_restart()
    server.ask_restart()
    assert asked == [1] and server.RESTART["asked"]
