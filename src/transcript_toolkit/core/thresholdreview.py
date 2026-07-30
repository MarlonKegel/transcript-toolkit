"""The threshold comparison: what each way of setting the bar would actually tag.

Choosing a rollup rule is a judgement about the collection, and it cannot be made from the
numbers in config.yaml. So the decision aid draws it: for every candidate rule, how many
interviews each topic (or place) would reach, with the bar that rule gives it. The three methods
get a panel each — the recommended one first and open, the other two folded away — and every
panel holds the variants worth comparing side by side.

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

HOW_TO_READ = (
    "One bar per {item}, longest at the top: how many interviews that {item} would be a tag of. "
    "The number beside a bar is that count and the bar it had to clear; the colour is the same "
    "threshold, so a panel where the colours vary is one where rare {items} are being asked for "
    "less. The number in brackets after a {item}'s name is how many clips it was tagged in "
    "across the whole collection — the frequency the bands are built from."
)

BAR_LEGEND = "the bar this {item} has to clear (% of the interview's clips)"

CURRENT_TAG = "what you have now"
NO_BAR = "#cfcfcf"          # an item that has no bar of its own to be coloured by


@dataclass(frozen=True)
class Variant:
    """One candidate rule, worked out against the real tags."""
    label: str
    rollup: Rollup
    thresholds: pd.Series          # item -> the bar it has to clear
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
    variants: list[Variant]
    items: str = TOPICS             # what this step tags, for the wording

    @property
    def title(self) -> str:
        return method_label(self.method, self.items)


def candidates(options: dict, current: Rollup) -> dict[str, list[Rollup]]:
    """The rules to compare, per method: every combination asked for, plus whatever is configured
    now — so the page always shows what you have beside what you could have."""
    out: dict[str, list[Rollup]] = {}
    for method in (FREQ_WIDTH, EQUAL_COUNT):
        out[method] = [Rollup(method=method, bins=bins, low=low, high=high)
                       for bins in options["bins"] for low, high in options["ranges"]]
    out[FLAT] = [Rollup(method=FLAT, threshold_pct=pct) for pct in options["flat"]]
    if current not in out[current.method]:
        out[current.method].append(current)
    return out


def label_for(rollup: Rollup, items: str = TOPICS) -> str:
    if rollup.method == FLAT:
        return f"{number(rollup.threshold_pct)}% for every {phrase('{item}', items)}"
    bars = rollup.bars()
    return (f"{len(bars)} bands · {number(bars[0])}–{number(bars[-1])}%"
            + (" · bars set by hand" if rollup.explicit else ""))


def build(options: dict, current: Rollup, evaluate, items: str = TOPICS) -> list[Panel]:
    """Work every candidate out against the collection. `evaluate(rollup)` is the step's own
    tagging — it returns (thresholds, reach, untagged) — so the picture is what a rollup with
    that rule would actually write, not an approximation of it."""
    panels = []
    for method in PANEL_ORDER:
        variants = []
        for rollup in candidates(options, current)[method]:
            thresholds, reach, untagged = evaluate(rollup)
            variants.append(Variant(label_for(rollup, items), rollup, thresholds, reach, untagged,
                                    current=rollup == current))
        panels.append(Panel(method, variants, items))
    return panels


# --- the figures --------------------------------------------------------------------------

def draw(panel: Panel, order: list[str], freq: pd.Series, out_path: Path, n_int: int) -> Path:
    """One figure per method: an axis per variant, sharing the list of topics down the side so
    the eye can run across a row and see what changes."""
    bars = [float(v) for variant in panel.variants for v in variant.thresholds
            if not pd.isna(v)]
    cmap = plt.cm.YlOrRd
    cnorm = mpl.colors.Normalize(vmin=min(bars, default=0.0), vmax=max(bars, default=1.0) or 1.0)
    y = np.arange(len(order))
    # Room past the longest bar for the count printed at its end, so it never runs off the edge.
    tallest = max((int(v.reach.max()) for v in panel.variants if len(v.reach)), default=0)
    widest = max(4.0, tallest * 1.2 + 1.5)

    def bar_of(variant: Variant, item: str) -> float:
        return float(variant.thresholds.get(item, float("nan")))

    fig, axes = plt.subplots(1, len(panel.variants),
                             figsize=(4.6 * len(panel.variants), max(5.0, 0.34 * len(order) + 1.6)),
                             sharey=True, squeeze=False)
    for ax, variant in zip(axes[0], panel.variants):
        reach = variant.reach
        # An item with no bar of its own (a place that only ever comes up inside a region) is
        # drawn grey rather than being given a number it was never judged by.
        ax.barh(y, [int(reach.get(t, 0)) for t in order],
                color=[NO_BAR if pd.isna(bar_of(variant, t)) else cmap(cnorm(bar_of(variant, t)))
                       for t in order], edgecolor="white")
        for t, yy in zip(order, y):
            bar = bar_of(variant, t)
            said = f"{int(reach.get(t, 0))}" + ("" if pd.isna(bar) else f" · {number(bar)}%")
            ax.text(int(reach.get(t, 0)) + 0.06, yy, said, va="center", fontsize=6.5)
        head = variant.label + (f"   ({CURRENT_TAG})" if variant.current else "")
        ax.set_title(f"{head}\n{variant.reached} of {len(order)} {panel.items} reached · "
                     f"{variant.tags} tags\n"
                     f"{variant.untagged} interviews with none at all",
                     fontsize=9, weight="bold" if variant.current else "normal")
        ax.set_xlabel(f"# interviews tagged (of {n_int})", fontsize=8.5)
        ax.set_xlim(0, widest)
        ax.spines[["top", "right"]].set_visible(False)
    axes[0][0].set_yticks(y)
    axes[0][0].set_yticklabels([f"{t}  ({int(freq.get(t, 0))})" for t in order], fontsize=8)
    scale = mpl.cm.ScalarMappable(cmap=cmap, norm=cnorm)
    scale.set_array([])
    fig.colorbar(scale, ax=axes[0], fraction=0.02, pad=0.015,
                 label=phrase(BAR_LEGEND, panel.items))
    # Above the axis titles rather than through them: those run to three lines, so the figure's
    # own heading has to be lifted clear of them (bbox_inches="tight" keeps it in the image).
    fig.suptitle(panel.title, fontsize=12, weight="bold", y=1.07)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return out_path


# --- the page -----------------------------------------------------------------------------

def write(step_dir: Path, name: str, *, title: str, subtitle: str, panels: list[Panel],
          order: list[str], freq: pd.Series, n_int: int, lead: str = "", extra: str = "") -> Path:
    """The comparison as one page: the figures, folded by method, and the numbers under them."""
    items = panels[0].items
    plots = step_dir / "plots"
    body = [f'<p class="lead">{reviewdoc.esc(lead)}</p>' if lead else "",
            reviewdoc.panel("How to read these",
                            f'<p class="lead">{reviewdoc.esc(phrase(HOW_TO_READ, items))}</p>')]
    for panel in panels:
        figure_path = draw(panel, order, freq, plots / f"{name}_{panel.method}.png", n_int)
        chosen = next((v for v in panel.variants if v.current), None)
        body.append(reviewdoc.panel(
            panel.title,
            reviewdoc.figure(f"plots/{figure_path.name}", panel.title),
            lead=method_blurb(panel.method, items),
            tag=(CURRENT_TAG if chosen else
                 ("recommended" if panel.method == RECOMMENDED else "")),
            tag_class="now" if chosen else "",
            open_=bool(chosen) or panel.method == RECOMMENDED))
    body.append(reviewdoc.panel("The numbers behind the pictures", _numbers(panels, n_int)))
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
