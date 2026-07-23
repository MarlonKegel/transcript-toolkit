"""Interactive confirmation for money-spending runs."""
from __future__ import annotations

import os
import subprocess
import sys

from ..errors import ToolkitError


def reveal(path) -> None:
    """Open a review file (or its folder) in the default app so non-technical users don't have to
    hunt for it — a browser for the .html, Finder for a directory. macOS only; a no-op elsewhere or
    when TOOLKIT_NO_OPEN=1. Best-effort: a failure to launch never breaks the run (the path was
    already printed)."""
    if sys.platform != "darwin" or os.environ.get("TOOLKIT_NO_OPEN") == "1":
        return
    subprocess.run(["open", str(path)], check=False)


def confirm_or_abort(question: str, yes: bool = False) -> None:
    """One [y/N] confirm before a full run. `--yes` or TOOLKIT_YES=1 skips it; a non-interactive
    session without either aborts (never silently spend money from a script)."""
    if yes or os.environ.get("TOOLKIT_YES") == "1":
        return
    if not sys.stdin.isatty():
        raise ToolkitError("Refusing to start a full run non-interactively without --yes.")
    answer = input(f"{question} [y/N] ").strip().lower()
    if answer not in ("y", "yes"):
        raise ToolkitError("Aborted.")
