"""A quiet "there's a newer version" notice.

The toolkit is installed from git, so there is no package index to ask — we read `__version__`
straight from the repo's raw file (a few dozen bytes, no auth, no API rate limit) and compare.

Three rules, because a version check must never be the reason a command fails or feels slow:
never raise, never block for more than a moment, and never update anything by itself. The result
is cached for a day, so at most one command per day pays for the lookup.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from .. import __version__

VERSION_URL = ("https://raw.githubusercontent.com/MarlonKegel/transcript-toolkit/"
               "main/src/transcript_toolkit/__init__.py")
CHECK_EVERY_S = 24 * 60 * 60
FETCH_TIMEOUT_S = 2.0
UPGRADE_COMMAND = "uv tool upgrade transcript-toolkit"
VERSION_TIMEOUT_S = 20.0

# What `toolkit update` says about itself when it is done. The app reads these to know whether
# to restart — a version that did not change is not worth interrupting anybody for.
UPDATED_MARKER = "Updated:"
UNCHANGED_MARKER = "Already the newest version — nothing changed."


def _cache_path() -> Path:
    return Path.home() / ".cache" / "transcript-toolkit" / "update_check.json"


# Where uv puts itself. PATH is checked first and is right whenever a person is typing; these are
# for when nobody is. An app opened from the Dock inherits launchd's environment, whose PATH is
# only /usr/bin:/bin:/usr/sbin:/sbin — the same reason app/launcher.py bakes in an absolute path
# for `toolkit`. Looking uv up on PATH alone means the update button can only ever fail there.
UV_DIRS = (
    "~/.local/bin",            # uv's own installer, and `uv tool install`'s bin directory
    "~/.cargo/bin",            # uv installed with cargo
    "/opt/homebrew/bin",       # Homebrew on Apple Silicon
    "/usr/local/bin",          # Homebrew on Intel, and manual installs
)


def uv_path() -> str | None:
    """The uv that owns this installation, as something runnable, or None if there is no uv."""
    import os
    import shutil

    found = shutil.which("uv")
    if found:
        return found
    for directory in (os.environ.get("UV_INSTALL_DIR"), *UV_DIRS):
        if not directory:
            continue
        candidate = Path(directory).expanduser() / "uv"
        if os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def parse_version(text: str) -> str | None:
    m = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    return m.group(1) if m else None


def version_tuple(v: str) -> tuple[int, ...]:
    """0.1.10 sorts above 0.1.9 (numeric compare, not string). Junk parts sort as 0."""
    return tuple(int(p) if p.isdigit() else 0 for p in v.split("."))


def _fetch_latest() -> str | None:
    from urllib.request import urlopen
    with urlopen(VERSION_URL, timeout=FETCH_TIMEOUT_S) as resp:      # noqa: S310 - fixed https URL
        return parse_version(resp.read(4096).decode("utf-8", "replace"))


def latest_version(force: bool = False) -> str | None:
    """The version on main, from cache when it was checked recently. None if unknown."""
    path = _cache_path()
    now = time.time()
    if not force:
        try:
            cached = json.loads(path.read_text())
            if now - float(cached["checked_at"]) < CHECK_EVERY_S:
                return cached.get("latest")
        except Exception:                       # no cache yet, or unreadable: just re-check
            pass
    latest = _fetch_latest()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"checked_at": now, "latest": latest}))
    except OSError:                             # read-only home: fine, we just re-check next time
        pass
    return latest


def update_notice(current: str = __version__) -> str | None:
    """The message to show, or None when up to date / offline / disabled."""
    if os.environ.get("TOOLKIT_NO_UPDATE_CHECK") == "1":
        return None
    try:
        latest = latest_version()
        if latest and version_tuple(latest) > version_tuple(current):
            return (f"\nA newer transcript-toolkit is available ({current} -> {latest}).\n"
                    f"Update with:  toolkit update")
    except Exception:                           # offline, DNS, timeout, GitHub down: stay silent
        return None
    return None


def print_update_notice() -> None:
    notice = update_notice()
    if notice:
        print(notice)


def tool_bin_dir() -> Path:
    """Where uv puts the commands it installs — `toolkit` among them."""
    import os

    for name in ("UV_TOOL_BIN_DIR", "XDG_BIN_HOME"):
        said = os.environ.get(name)
        if said:
            return Path(said).expanduser()
    return Path.home() / ".local" / "bin"


def _uv_env() -> dict:
    """The environment to run uv in.

    When uv had to be found off PATH we are not being driven by a shell — the app was opened
    from the Dock, where macOS hands out `/usr/bin:/bin:/usr/sbin:/sbin` and nothing else. uv
    checks its own bin directory against PATH and warns that installed tools will not be found,
    which is true of that PATH and irrelevant to this situation: the app runs `toolkit` by
    absolute path. Telling uv where its tools go stops it giving an instruction that would only
    confuse whoever is reading. In a terminal, where uv IS on PATH, the warning is real advice
    and is left alone.
    """
    import os
    import shutil

    env = dict(os.environ)
    if shutil.which("uv") is None:
        env["PATH"] = os.pathsep.join([str(tool_bin_dir()), env.get("PATH", "")]).rstrip(os.pathsep)
    return env


def run_update() -> None:
    """`toolkit update` — do the thing people type when they want a newer version.

    Shells out to uv rather than reimplementing anything: uv owns the installation. If uv isn't
    driving this install (a dev checkout, or pip), say so and print the command instead of
    guessing at someone's environment."""
    import subprocess

    from ..errors import ToolkitError

    uv = uv_path()
    if uv is None:
        raise ToolkitError(
            f"uv is not installed on this Mac, so this copy was not installed with it.\n"
            f"If you followed the setup guide, install uv and run:  {UPGRADE_COMMAND}\n"
            f"If this is a development checkout, update it with git instead.")

    print(f"Current version: {__version__}")
    print(f"Running: {UPGRADE_COMMAND}\n")
    result = subprocess.run([uv, *UPGRADE_COMMAND.split()[1:]], check=False, env=_uv_env())
    if result.returncode != 0:
        raise ToolkitError(
            f"uv could not upgrade this install (exit code {result.returncode}). If you installed "
            f"the toolkit some other way, update it that way instead.")
    _cache_path().unlink(missing_ok=True)          # the "newer version" notice is now stale
    installed = installed_version()
    if installed and installed != __version__:
        # Said in the toolkit's own words rather than left to uv's: this line is what the app
        # reads to know it should restart itself, and parsing another program's prose for that
        # would be a promise about uv's output nobody made.
        print(f"\n{UPDATED_MARKER} {__version__} -> {installed}")
    else:
        print(f"\n{UNCHANGED_MARKER}")
    print("Check it with:  toolkit --version")


def installed_version() -> str | None:
    """The version now on disk, by asking the command uv just replaced.

    Not `__version__`: this process loaded that before the upgrade and cannot see the new code.
    A fresh subprocess can, which is why it is worth the second or so it takes.
    """
    import subprocess

    toolkit = tool_bin_dir() / "toolkit"
    if not toolkit.exists():
        return None
    try:
        said = subprocess.run([str(toolkit), "--version"], capture_output=True, text=True,
                              timeout=VERSION_TIMEOUT_S, check=False, env=_uv_env())
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_reported_version(said.stdout or said.stderr)


def parse_reported_version(said: str) -> str | None:
    """`toolkit --version` prints `transcript-toolkit 0.2.9`."""
    parts = said.strip().split()
    return parts[-1] if parts else None
