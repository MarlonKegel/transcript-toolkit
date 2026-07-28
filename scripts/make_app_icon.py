#!/usr/bin/env python3
"""Draw the app icon (defaults/app/icon.png), so it is reproducible rather than a binary
that appeared from nowhere.

Shape language: a transcript — a stack of lines — with the middle band picked out in the
accent colour, the way the pipeline picks a clip out of an interview. Deliberately bold: this
is rendered at 16 px in the Dock as often as at 512.

    python scripts/make_app_icon.py
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt                                    # noqa: E402
from matplotlib.patches import FancyBboxPatch                      # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "src" / "transcript_toolkit" / "defaults" / "app" / "icon.png"
SIZE_PX = 1024

INK = "#1e2340"          # deep navy background
PAPER = "#f6f7fb"        # the transcript lines
ACCENT = "#ff8a4c"       # the highlighted clip
MUTED = "#7b86b8"        # secondary lines

# (y, width, colour) — a stack of lines with one band called out. Widths vary so it reads as
# text rather than a barcode.
LINES = [
    (0.735, 0.52, MUTED),
    (0.625, 0.72, PAPER),
    (0.515, 0.62, PAPER),
    (0.385, 0.78, ACCENT),
    (0.275, 0.55, ACCENT),
    (0.165, 0.40, MUTED),
]
BAR_H = 0.072
INSET = 0.11             # transparent margin, as macOS icons have


def main() -> None:
    fig = plt.figure(figsize=(SIZE_PX / 100, SIZE_PX / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    fig.patch.set_alpha(0)

    side = 1 - 2 * INSET
    ax.add_patch(FancyBboxPatch(
        (INSET, INSET), side, side,
        boxstyle="round,pad=0,rounding_size=0.20", linewidth=0, facecolor=INK))

    left = INSET + 0.085
    usable = side - 0.17
    for y, width, colour in LINES:
        ax.add_patch(FancyBboxPatch(
            (left, INSET + y * side - BAR_H / 2), usable * width, BAR_H * side,
            boxstyle="round,pad=0,rounding_size=0.030", linewidth=0, facecolor=colour))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, transparent=True, dpi=100)
    plt.close(fig)
    print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
