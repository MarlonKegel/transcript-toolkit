"""The threshold comparison: what each way of setting the threshold would actually tag.

Choosing a rollup rule is a judgement about the collection, and it cannot be made from the
numbers in config.yaml. So the decision aid draws it: for every candidate rule, how many
interviews each topic (or place) would reach, with the threshold that rule gives it. The three
methods get a panel each — the recommended one first and open, the other two folded away.

Within a binned panel the variants are laid out as a grid: one row per number of bins, one
column per range. They vary along exactly those two axes, so reading across a row and down a
column is the comparison, and a single line of four would hide it.

Both `toolkit topics thresholds` and `toolkit locations thresholds` render through here. What
differs between them is only how a rule turns into tags, which each step passes in.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import matplotlib
matplotlib.use("Agg")                                          # noqa: E402 - before pyplot
import matplotlib as mpl                                       # noqa: E402
import matplotlib.pyplot as plt                                # noqa: E402
import numpy as np                                             # noqa: E402
import pandas as pd                                            # noqa: E402

from . import reviewdoc                                        # noqa: E402
from .thresholds import (EQUAL_COUNT, FLAT, FREQ_WIDTH, RECOMMENDED, TOPICS,  # noqa: E402
                         Rollup, method_blurb, method_label, number, phrase)

PANEL_ORDER = (FREQ_WIDTH, EQUAL_COUNT, FLAT)

# The one explanation on the page: what is being decided, and how to read the pictures that help
# you decide it. Short, above everything, and not folded away behind a summary that looks like
# the panels holding the actual plots.
LEAD = (
    "A {item} becomes one of an interview's tags once enough of that interview's clips were "
    "tagged with it. This is where you decide what counts as enough. Each panel below is one way "
    "of deciding, drawn against your real results.\n\n"
    "In every picture there is one bar per {item}, longest at the top: how many interviews that "
    "{item} would end up tagged in. Beside each bar is that count and the threshold the {item} "
    "had to clear, and the colour is that same threshold — so a picture with varied colours is "
    "one where rarer {items} are being asked for less. In brackets after a {item}'s name is how "
    "many clips it was tagged in across the whole collection, which is the frequency the bins are "
    "built from.\n\n"
    "Open the one you like, set it under '{choose}', and roll up."
)

CHOOSE_STEP = "Roll up to interview tags"

CURRENT_TAG = "what your results were built with"
RECOMMENDED_TAG = "recommended"
NO_BAR = "#cfcfcf"          # an item that has no threshold of its own to be coloured by


@dataclass(frozen=True)
class Variant:
    """One candidate rule, worked out against the real tags."""
    label: str
    rollup: Rollup
    thresholds: pd.Series          # item -> the threshold it has to clear
    reach: pd.Series               # item -> how many interviews it would be a tag of
    untagged: int                  # interviews that would come out with nothing at all
    current: bool = False

    @property
    def reached(self) -> int:
        return int((self.reach > 0).sum())

    @property
    def tags(self) -> int:
        return int(self.reach.sum())


@dataclass(frozen=True)
class Panel:
    method: str
    grid: list[list[Variant]]       # rows of variants; a binned panel is bins x ranges
    items: str = TOPICS             # what this step tags, for the wording

    @property
    def title(self) -> str:
        return method_label(self.method, self.items)

    @property
    def variants(self) -> list[Variant]:
        return [v for row in self.grid for v in row]


def candidates(options: dict, current: Rollup | None) -> dict[str, list[list[Rollup]]]:
    """The rules to compare, per method, as a grid.

    Whatever the results on disk were built with is folded into its own method's axes rather
    than tacked on the end, so it can be read against the alternatives along both dimensions.
    """
    bins, ranges, flat = list(options["bins"]), list(options["ranges"]), list(options["flat"])
    if current is not None and not current.explicit:
        if current.method == FLAT:
            if current.threshold_pct not in flat:
                flat.append(current.threshold_pct)
        else:
            if current.bins not in bins:
                bins.append(current.bins)
            if (current.low, current.high) not in ranges:
                ranges.append((current.low, current.high))
    out: dict[str, list[list[Rollup]]] = {}
    for method in (FREQ_WIDTH, EQUAL_COUNT):
        out[method] = [[Rollup(method=method, bins=n, low=low, high=high)
                        for low, high in ranges] for n in sorted(bins)]
    out[FLAT] = [[Rollup(method=FLAT, threshold_pct=pct) for pct in sorted(flat)]]
    # A hand-written threshold list belongs to no row and no column, so it gets a row of its own.
    if current is not None and current.explicit:
        out[current.method] = [*out[current.method], [current]]
    return out


def label_for(rollup: Rollup, items: str = TOPICS) -> str:
    if rollup.method == FLAT:
        return f"{number(rollup.threshold_pct)}% for every {phrase('{item}', items)}"
    bars = rollup.bars()
    return (f"{len(bars)} bins · {number(bars[0])}–{number(bars[-1])}%"
            + (" · set by hand" if rollup.explicit else ""))


def build(options: dict, current: Rollup | None, evaluate, items: str = TOPICS) -> list[Panel]:
    """Work every candidate out against the collection. `evaluate(rollup)` is the step's own
    tagging — it returns (thresholds, reach, untagged) — so the picture is what a rollup with
    that rule would actually write, not an approximation of it.

    `current` is the rule the results on disk were built with, or None when nothing has been
    rolled up yet — in which case nothing is marked, because nothing is true of the project yet.
    """
    grids = candidates(options, current)
    panels = []
    for method in PANEL_ORDER:
        rows = []
        for row in grids[method]:
            built = []
            for rollup in row:
                thresholds, reach, untagged = evaluate(rollup)
                built.append(Variant(label_for(rollup, items), rollup, thresholds, reach,
                                     untagged, current=rollup == current))
            rows.append(built)
        panels.append(Panel(method, rows, items))
    return panels


# --- the figures --------------------------------------------------------------------------

def draw(panel: Panel, order: list[str], freq: pd.Series, out_path: Path, n_int: int) -> Path:
    """One figure per method: the variants as a grid, sharing the list of topics down the side so
    the eye can run across a row and see what changes."""
    bars = [float(v) for variant in panel.variants for v in variant.thresholds
            if not pd.isna(v)]
    cmap = plt.cm.YlOrRd
    cnorm = mpl.colors.Normalize(vmin=min(bars, default=0.0), vmax=max(bars, default=1.0) or 1.0)
    y = np.arange(len(order))
    # Room past the longest bar for the count printed at its end, so it never runs off the edge.
    tallest = max((int(v.reach.max()) for v in panel.variants if len(v.reach)), default=0)
    widest = max(4.0, tallest * 1.2 + 1.5)

    n_rows = len(panel.grid)
    n_cols = max(len(row) for row in panel.grid)
    row_height = max(4.6, 0.30 * len(order) + 1.9)
    # Constrained layout, not tight: it reserves room for the figure's own heading and the
    # colorbar, which otherwise leave a hand's width of blank paper above a two-row grid.
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(4.6 * n_cols, row_height * n_rows),
                             sharex=True, sharey=True, squeeze=False, layout="constrained")

    def bar_of(variant: Variant, item: str) -> float:
        return float(variant.thresholds.get(item, float("nan")))

    for r, row in enumerate(panel.grid):
        for c in range(n_cols):
            ax = axes[r][c]
            if c >= len(row):                       # a ragged last row: leave the cell empty
                ax.set_visible(False)
                continue
            variant = row[c]
            reach = variant.reach
            # An item with no threshold of its own (a place that only ever comes up inside a
            # region) is drawn grey rather than given a number it was never judged by.
            ax.barh(y, [int(reach.get(t, 0)) for t in order],
                    color=[NO_BAR if pd.isna(bar_of(variant, t))
                           else cmap(cnorm(bar_of(variant, t))) for t in order],
                    edgecolor="white")
            for t, yy in zip(order, y):
                bar = bar_of(variant, t)
                said = f"{int(reach.get(t, 0))}" + ("" if pd.isna(bar) else f" · {number(bar)}%")
                ax.text(int(reach.get(t, 0)) + 0.06, yy, said, va="center", fontsize=6.5)
            head = variant.label + (f"   ({CURRENT_TAG})" if variant.current else "")
            ax.set_title(f"{head}\n{variant.reached} of {len(order)} {panel.items} reached · "
                         f"{variant.tags} tags\n"
                         f"{variant.untagged} interviews with none at all",
                         fontsize=9, weight="bold" if variant.current else "normal")
            ax.set_xlim(0, widest)
            ax.spines[["top", "right"]].set_visible(False)
            if r == n_rows - 1:
                ax.set_xlabel(f"# interviews tagged (of {n_int})", fontsize=8.5)
            if c == 0:
                ax.set_yticks(y)
                ax.set_yticklabels([f"{t}  ({int(freq.get(t, 0))})" for t in order], fontsize=8)

    scale = mpl.cm.ScalarMappable(cmap=cmap, norm=cnorm)
    scale.set_array([])
    fig.colorbar(scale, ax=axes, fraction=0.02, pad=0.015,
                 label=phrase(BAR_LEGEND, panel.items))
    fig.suptitle(panel.title, fontsize=12, weight="bold")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=140)
    plt.close(fig)
    return out_path


BAR_LEGEND = "the threshold this {item} has to clear (% of the interview's clips)"


# --- the page -----------------------------------------------------------------------------

def write(step_dir: Path, name: str, *, title: str, subtitle: str, panels: list[Panel],
          order: list[str], freq: pd.Series, n_int: int, choose: str = CHOOSE_STEP,
          extra: str = "") -> Path:
    """The comparison as one page: the explanation, the figures folded by method, and the same
    numbers as a table underneath."""
    items = panels[0].items
    plots = step_dir / "plots"
    body = [f'<p class="lead">{reviewdoc.esc(phrase(LEAD, items, choose=choose))}</p>']
    for panel in panels:
        figure_path = draw(panel, order, freq, plots / f"{name}_{panel.method}.png", n_int)
        chosen = next((v for v in panel.variants if v.current), None)
        tags = []
        if panel.method == RECOMMENDED:
            tags.append((RECOMMENDED_TAG, ""))
        if chosen:
            tags.append((CURRENT_TAG, "now"))
        body.append(reviewdoc.panel(
            panel.title,
            reviewdoc.figure(f"plots/{figure_path.name}", panel.title),
            lead=method_blurb(panel.method, items),
            tags=tags,
            open_=bool(chosen) or panel.method == RECOMMENDED))
    body.append(reviewdoc.panel("The same comparison as a table", _numbers(panels, n_int),
                                aside=True))
    if extra:
        body.append(extra)

    step_dir.mkdir(parents=True, exist_ok=True)
    out = step_dir / f"{name}_thresholds.html"
    out.write_text(reviewdoc.document(title, "\n".join(p for p in body if p),
                                      subtitle=reviewdoc.esc(subtitle)))
    return out


def _numbers(panels: list[Panel], n_int: int) -> str:
    rows = []
    for panel in panels:
        for variant in panel.variants:
            rows.append([panel.title + (f"  ({CURRENT_TAG})" if variant.current else ""),
                         variant.label, f"{variant.reached}", f"{variant.tags}",
                         f"{variant.untagged}"])
    return reviewdoc.table(
        ["Method", "Variant", f"{panels[0].items.title()} reached", "Tags in total",
         f"Interviews with none (of {n_int})"], rows, numeric={2, 3, 4})


def report(panels: list[Panel], n_int: int) -> None:
    """The same numbers in the terminal, for whoever is not looking at the page."""
    width = max(len(v.label) for panel in panels for v in panel.variants)
    for panel in panels:
        print(f"\n{panel.title}")
        for variant in panel.variants:
            mark = f"  <- {CURRENT_TAG}" if variant.current else ""
            print(f"  {variant.label:<{width}}  {variant.reached:>3} {panel.items} reached · "
                  f"{variant.tags:>4} tags · {variant.untagged:>3} of {n_int} interviews "
                  f"with none{mark}")
