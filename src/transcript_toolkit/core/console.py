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


def _money(v: float | None) -> str:
    return f"~${v:.2f}" if v is not None else "cost unknown"


def choose_transport(summary: str, est: tuple[float, float] | None = None, yes: bool = False,
                     batch: bool | None = None) -> bool:
    """The full-run gate for steps that can also run on the Batch API: confirm the spend AND pick
    the transport in one prompt. Returns True for the Batch API, False to run now.

    `est` is (standard_usd, batch_usd) from cost.estimate_pair, or None when there's nothing to
    extrapolate from (the figures are then omitted rather than guessed). An explicit
    `--batch`/`--no-batch` fixes the transport and downgrades this to a plain spend confirm;
    `--yes`/TOOLKIT_YES=1 skips the prompt entirely and honours `batch` (default: run now).
    Non-interactive without `--yes` aborts — never silently spend money from a script."""
    if yes or os.environ.get("TOOLKIT_YES") == "1":
        return bool(batch)
    if not sys.stdin.isatty():
        raise ToolkitError("Refusing to start a full run non-interactively without --yes.")

    std = f"  {_money(est[0] if est else None)}"
    bat = f"  {_money(est[1] if est else None)}"
    if batch is not None:                       # transport already chosen; just confirm the spend
        which = f"the Batch API{bat}" if batch else f"synchronous calls{std}"
        if input(f"{summary}\nRun with {which}? [y/N] ").strip().lower() not in ("y", "yes"):
            raise ToolkitError("Aborted.")
        return batch

    print(summary)
    print(f"  [1] Run now     {std}   results in this session")
    print(f"  [2] Batch API   {bat}   50% cheaper, up to 24h turnaround")
    print("  [n] Cancel")
    answer = input("Choose [1/2/n] ").strip().lower()
    if answer in ("1", "y", "yes"):
        return False
    if answer == "2":
        return True
    raise ToolkitError("Aborted.")
