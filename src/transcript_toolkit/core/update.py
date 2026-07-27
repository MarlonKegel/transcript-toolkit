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


def _cache_path() -> Path:
    return Path.home() / ".cache" / "transcript-toolkit" / "update_check.json"


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
                    f"Update with:  {UPGRADE_COMMAND}")
    except Exception:                           # offline, DNS, timeout, GitHub down: stay silent
        return None
    return None


def print_update_notice() -> None:
    notice = update_notice()
    if notice:
        print(notice)
