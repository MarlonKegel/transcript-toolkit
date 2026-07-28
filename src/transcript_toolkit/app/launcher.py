"""Build the double-clickable Mac launcher.

The app is not downloaded — it is *made here*, on the user's own Mac, out of parts macOS
already ships (osacompile, sips, iconutil, codesign). That is the whole point: macOS refuses
to open downloaded apps that aren't signed by a paid Apple developer account, but a bundle
created locally is never quarantined, so it opens on the first double-click with no warning
at all. Verified on macOS 26.5 (2026-07-28) — see scripts/mac_launcher_smoke_test.sh.

Three details are load-bearing, each learned from that test:

- **Absolute paths.** An app launched from Finder inherits launchd's environment, where PATH
  is only /usr/bin:/bin:/usr/sbin:/sbin — `toolkit` is not on it. The full path is baked in.
- **Detach, then quit.** The launcher backgrounds the server with its output redirected and
  exits immediately, so the server keeps running (through sleep, for hours) with no app
  sitting in the Dock.
- **Sign last.** Editing Info.plist or the icon after osacompile invalidates the signature,
  and Apple Silicon refuses to run a bundle whose signature doesn't match. Re-signing is the
  final step.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from importlib import resources
from pathlib import Path

from ..errors import ToolkitError
from . import DEFAULT_PORT

APP_NAME = "Transcript Toolkit"
BUNDLE_ID = "org.incite.transcript-toolkit"
ICON_SIZES = (16, 32, 128, 256, 512)


def applications_dir() -> Path:
    return Path.home() / "Applications"


def app_path() -> Path:
    return applications_dir() / f"{APP_NAME}.app"


def log_path() -> Path:
    return Path.home() / "Library" / "Logs" / "transcript-toolkit" / "launch.log"


def toolkit_command() -> Path:
    """The absolute path of the installed `toolkit` command, which the launcher will call."""
    found = shutil.which("toolkit")
    if found:
        return Path(found).resolve()
    uv = shutil.which("uv")
    if uv:
        result = subprocess.run([uv, "tool", "dir", "--bin"], capture_output=True, text=True)
        candidate = Path(result.stdout.strip() or "/nonexistent") / "toolkit"
        if candidate.exists():
            return candidate.resolve()
    raise ToolkitError(
        "Cannot find the `toolkit` command to point the launcher at. Install the toolkit with:\n"
        "  uv tool install git+https://github.com/MarlonKegel/transcript-toolkit.git\n"
        "then run this again.")


START_TIMEOUT_S = 40


def applescript(command: Path, log: Path, port: int | None = None) -> str:
    """The launcher's whole program: start the server in the background, wait until it
    answers, and quit — or say what went wrong.

    The waiting is the important half. Backgrounding alone would make every startup failure
    invisible: a double-click that does nothing at all, with the explanation buried in a log
    file, is not something this app's users can recover from. So the applet asks the server
    for a sign of life and, if none comes, shows the end of the log in a dialog.

    Every path is single-quoted for the shell, and the background job's output is fully
    redirected — otherwise the launcher would sit there waiting for a server that runs for
    hours.
    """
    port_arg = f" --port {port}" if port else ""
    where = f"http://127.0.0.1:{port or DEFAULT_PORT}/api/health"
    shell = (
        # The folder has to exist before the redirect is set up, so mkdir runs outside it.
        f"/bin/mkdir -p '{log.parent}'; "
        f"'{command}' app --from-launcher{port_arg} > '{log}' 2>&1 & "
        f"n=0; while [ $n -lt {START_TIMEOUT_S} ]; do "
        f"/usr/bin/curl -sf -m 2 '{where}' 2>/dev/null | /usr/bin/grep -q transcript-toolkit "
        f"&& exit 0; n=$((n+1)); /bin/sleep 1; done; "
        f"echo 'It did not start. The end of its log:' >&2; "
        f"/usr/bin/tail -15 '{log}' >&2; exit 1"
    )
    return (
        'on run\n'
        '\ttry\n'
        f'\t\tdo shell script "{shell}"\n'
        '\ton error errMsg\n'
        f'\t\tdisplay alert "{APP_NAME} could not start" message errMsg & '
        f'"\\n\\nFull log: {log}"\n'
        '\tend try\n'
        'end run\n'
    )


def _run(argv: list[str], what: str) -> None:
    result = subprocess.run(argv, capture_output=True, text=True)
    if result.returncode != 0:
        raise ToolkitError(f"Could not {what}: {result.stderr.strip() or result.stdout.strip()}\n"
                           f"(command: {' '.join(argv)})")


def _write_icon(bundle: Path, work: Path) -> None:
    """Swap in the toolkit's icon. On recent macOS an applet carries a compiled asset catalog
    that wins over the .icns file, so that has to go for the icon to show up at all."""
    source = resources.files("transcript_toolkit") / "defaults" / "app" / "icon.png"
    png = work / "icon.png"
    png.write_bytes(source.read_bytes())

    iconset = work / "icon.iconset"
    iconset.mkdir()
    for size in ICON_SIZES:
        for name, px in ((f"icon_{size}x{size}.png", size), (f"icon_{size}x{size}@2x.png", size * 2)):
            _run(["sips", "-z", str(px), str(px), str(png), "--out", str(iconset / name)],
                 "resize the icon")
    _run(["iconutil", "-c", "icns", "-o", str(work / "applet.icns"), str(iconset)],
         "build the icon file")

    (bundle / "Contents" / "Resources" / "applet.icns").write_bytes((work / "applet.icns").read_bytes())
    (bundle / "Contents" / "Resources" / "Assets.car").unlink(missing_ok=True)


def _set_plist(bundle: Path, key: str, value: str) -> None:
    plist = bundle / "Contents" / "Info.plist"
    for verb in (f'Set :{key} {value}', f'Add :{key} string {value}'):
        result = subprocess.run(["/usr/libexec/PlistBuddy", "-c", verb, str(plist)],
                                capture_output=True, text=True)
        if result.returncode == 0:
            return
    raise ToolkitError(f"Could not set {key} in {plist}")


def install_launcher(port: int | None = None) -> Path:
    """Create (or replace) the launcher app and return where it landed."""
    import tempfile

    if sys.platform != "darwin":
        raise ToolkitError("The launcher app is a macOS thing. On this system, start the app "
                           "with:  toolkit app")

    command = toolkit_command()
    bundle = app_path()
    applications_dir().mkdir(parents=True, exist_ok=True)
    log_path().parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        script = work / "launcher.applescript"
        script.write_text(applescript(command, log_path(), port))

        if bundle.exists():
            shutil.rmtree(bundle)       # a fresh bundle, so nothing stale survives an update
        _run(["osacompile", "-o", str(bundle), str(script)], "build the launcher app")

        _set_plist(bundle, "CFBundleIdentifier", BUNDLE_ID)
        _set_plist(bundle, "CFBundleName", f'"{APP_NAME}"')
        _write_icon(bundle, work)
        bundle.touch()                  # nudge Finder to notice the new icon
        # Last, always: the edits above break the signature osacompile left behind, and macOS
        # will not launch a bundle whose signature doesn't match its contents.
        _run(["codesign", "--force", "-s", "-", str(bundle)], "sign the launcher app")

    return bundle
