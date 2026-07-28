"""Starting, finding and stopping the local app server.

The server is a plain web server on the loopback address: nothing is exposed to the network,
no data leaves the Mac, and there is nothing to host. It outlives the browser tab on purpose —
a corpus run takes hours, and closing a window should not cancel it.
"""
from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
import webbrowser
from importlib import resources
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse

from .. import __version__
from ..errors import ToolkitError
from ..project import find_project
from .context import CONTEXT, DEFAULT_PORT

MARKER = "transcript-toolkit"
QUIT_HEADER = "x-toolkit-quit"
PROBE_TIMEOUT_S = 1.5
SHUTDOWN_WAIT_S = 10.0

FREE, OURS, FOREIGN = "free", "ours", "foreign"


def url(port: int) -> str:
    return f"http://127.0.0.1:{port}/"


def occupant(port: int) -> tuple[str, dict | None]:
    """Who has the port: nobody, another copy of this app, or something unrelated."""
    with socket.socket() as probe:
        probe.settimeout(PROBE_TIMEOUT_S)
        if probe.connect_ex(("127.0.0.1", port)) != 0:
            return FREE, None
    try:
        with urllib.request.urlopen(f"{url(port)}api/health",       # noqa: S310 - loopback only
                                    timeout=PROBE_TIMEOUT_S) as response:
            data = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return FOREIGN, None
    return (OURS, data) if data.get("app") == MARKER else (FOREIGN, None)


def _ask_to_quit(port: int) -> None:
    """Tell an older copy of the app to stop, so an updated one can take the port."""
    request = urllib.request.Request(f"{url(port)}api/quit", method="POST",
                                     headers={QUIT_HEADER: "1"})
    try:
        urllib.request.urlopen(request, timeout=PROBE_TIMEOUT_S).close()   # noqa: S310
    except (urllib.error.URLError, TimeoutError, OSError):
        pass                # a server that dies mid-reply is exactly what we asked it to do
    deadline = time.time() + SHUTDOWN_WAIT_S
    while time.time() < deadline:
        if occupant(port)[0] == FREE:
            return
        time.sleep(0.3)
    raise ToolkitError(
        f"An older copy of the toolkit is still using port {port} and did not stop when asked. "
        f"Quit it from its own window (Settings -> Quit), then try again.")


def _resolve_workspace(explicit: str | None):
    """Which project to open: the one asked for, the one we are standing in, or the one used
    last. None is fine — the app then opens on the workspace page."""
    from . import workspaces

    if explicit:
        return find_project(explicit)
    try:
        return find_project()                       # started from inside a workspace
    except ToolkitError:
        pass
    for entry in workspaces.load_registry():
        candidate = Path(entry["path"])
        if (candidate / ".toolkit" / "project.json").exists():
            return find_project(str(candidate))
    return None


def _register_routes() -> None:
    from nicegui import app

    @app.get("/api/health")
    def health() -> dict:                                           # noqa: D401
        """Lets a second launch recognise this server instead of starting another."""
        return {"app": MARKER, "version": __version__, "port": CONTEXT.port,
                "workspace": str(CONTEXT.project.root) if CONTEXT.project else None}

    @app.post("/api/quit")
    def quit_server(request: Request) -> dict:
        # The header is what makes this unreachable from a web page the user happens to have
        # open: a cross-origin request carrying a custom header needs permission this server
        # never grants, so only the toolkit itself can ask.
        if request.headers.get(QUIT_HEADER) != "1":
            raise HTTPException(status_code=403, detail="Quit the toolkit from its own window.")
        app.shutdown()
        return {"stopping": True}

    @app.get("/diags/{path:path}")
    def diagnostics(path: str) -> FileResponse:
        """Serve the review pages out of the open workspace's diags/ folder."""
        if CONTEXT.project is None:
            raise HTTPException(status_code=404, detail="No workspace is open.")
        root = CONTEXT.project.diags_dir.resolve()
        target = (root / path).resolve()
        if not target.is_file() or not target.is_relative_to(root):
            raise HTTPException(status_code=404, detail="No such review page.")
        return FileResponse(target)


def build() -> None:
    """Assemble the app: every page and every route, and nothing that starts a server.

    Separate from `serve` so the tests can drive the same app the user gets.
    """
    from .pages import export, home, settings, step, workspace

    for page in (home, workspace, step, export, settings):
        page.register()
    _register_routes()


def serve(project: str | None = None, port: int = DEFAULT_PORT, open_browser: bool = True,
          from_launcher: bool = False) -> None:
    """Run the app, or hand over to the copy that is already running."""
    state, data = occupant(port)
    if state == OURS:
        if data and data.get("version") != __version__:
            print(f"Replacing the running toolkit {data.get('version')} with {__version__}.")
            _ask_to_quit(port)
        else:
            print(f"The toolkit is already running — opening {url(port)}")
            if open_browser:
                webbrowser.open(url(port))
            return
    elif state == FOREIGN:
        raise ToolkitError(
            f"Port {port} on this Mac is already used by another program, so the toolkit "
            f"cannot start there.\nStart it on a different port with:\n"
            f"  toolkit app --port {port + 1}\n"
            f"To make the desktop app use that port from now on:\n"
            f"  toolkit app --install-launcher --port {port + 1}")

    CONTEXT.port = port
    CONTEXT.project = _resolve_workspace(project)

    from nicegui import ui

    build()
    icon = resources.files("transcript_toolkit") / "defaults" / "app" / "icon.png"
    # Named in the log because when a colleague's Mac misbehaves, the first question is
    # whether the app was started by the desktop icon or by hand.
    print(f"Started {'from the desktop app' if from_launcher else 'from the command line'}.")
    print(f"Transcript Toolkit {__version__} — {url(port)}\n"
          f"Leave this running while you work. Close it from the app's Settings page, or with "
          f"Ctrl-C here.")
    ui.run(host="127.0.0.1", port=port, title="Transcript Toolkit", favicon=Path(str(icon)),
           show=open_browser, reload=False, dark=None, storage_secret=None)
