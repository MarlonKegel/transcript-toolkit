"""Interactive confirmation for money-spending runs."""
from __future__ import annotations

import os
import sys

from ..errors import ToolkitError


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
