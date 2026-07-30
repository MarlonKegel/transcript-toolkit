"""How a clip-level tag becomes an interview-level tag: the rollup rule, in one place.

An interview is tagged when the share of its clips carrying that tag clears a bar. The question
is which bar, and the answer is a *method* rather than a hand-written list of numbers:

  freq_width   — the recommended one. The items are split into equal-width bands by how often
                 they come up across the collection, and a rarer band clears a lower bar. Rare
                 topics get off zero without common ones being tagged everywhere. Two items that
                 come up equally often always share a bar.
  equal_count  — the same idea, but each band holds the same NUMBER of items rather than covering
                 the same width of frequency. Two equally-frequent items can land in different
                 bands and get different bars, which is why it is the advanced option.
  flat         — one bar for every item. Simple to explain; rare items rarely clear it.

A binned method is described by how many bands and over what range (`bins`, `range: [lo, hi]`),
and the bars are derived from those — evenly spaced, rarest band first. 5 bins over 10-30% is
[10, 15, 20, 25, 30]; 9 bins is [10, 12.5, ..., 30]. Topics and locations share all of this.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..errors import ToolkitError

FREQ_WIDTH, EQUAL_COUNT, FLAT = "freq_width", "equal_count", "flat"
METHODS = (FREQ_WIDTH, EQUAL_COUNT, FLAT)

# What each method is called and what it does, in the words the app and the review pages use.
# One wording, in one place, so the settings control and the comparison page cannot disagree.
# `{item}` / `{items}` are what is being tagged: topics on one page, places on the other.
METHOD_LABEL = {
    FREQ_WIDTH: "A lower bar for rarer {items}",
    EQUAL_COUNT: "A lower bar for rarer {items}, in equal-sized groups",
    FLAT: "One bar for every {item}",
}
METHOD_BLURB = {
    FREQ_WIDTH:
        "The recommended one. The {items} are sorted by how often they come up across the whole "
        "collection and split into bands of equal width; the rarest band clears the lowest bar "
        "and the commonest the highest. A {item} that only comes up here and there can still "
        "become an interview's tag, without the common ones being tagged everywhere. Two {items} "
        "that come up equally often always get the same bar.",
    EQUAL_COUNT:
        "The same idea, except every band holds the same number of {items} rather than covering "
        "the same range of frequency. It spreads the bars evenly over your list, but two {items} "
        "that come up exactly as often can end up in different bands and be judged differently. "
        "Worth comparing; not the one to start with.",
    FLAT:
        "Every {item} needs the same share of an interview's clips. It is the easiest to explain "
        "to a reader, and the reason for the other two: at a bar high enough to keep common "
        "{items} meaningful, rare {items} almost never reach it.",
}

RECOMMENDED = FREQ_WIDTH

TOPICS, PLACES = "topics", "places"
SINGULAR = {TOPICS: "topic", PLACES: "place"}


def phrase(text: str, items: str = TOPICS) -> str:
    """One of the wordings above, about whatever this step tags."""
    return text.format(item=SINGULAR[items], items=items)


def method_label(method: str, items: str = TOPICS) -> str:
    return phrase(METHOD_LABEL[method], items)


def method_blurb(method: str, items: str = TOPICS) -> str:
    return phrase(METHOD_BLURB[method], items)

# Where a new project starts: rarity bins, five bands, 10-30% of an interview's clips.
DEFAULT_BINS = 5
DEFAULT_RANGE = (10.0, 30.0)
DEFAULT_FLAT_PCT = 30.0

# What `toolkit topics thresholds` / `toolkit locations thresholds` draw when nothing says
# otherwise. Projects can change them in advanced/<step>.yaml under `compare`; a run can
# override them with --bins / --ranges / --flat.
COMPARE_BINS = (5, 9)
COMPARE_RANGES = ((10.0, 30.0), (20.0, 40.0))
COMPARE_FLAT = (20.0, 30.0, 40.0)


@dataclass(frozen=True)
class Rollup:
    """The rule for turning clip tags into interview tags, as config states it."""
    method: str = RECOMMENDED
    bins: int = DEFAULT_BINS
    low: float = DEFAULT_RANGE[0]
    high: float = DEFAULT_RANGE[1]
    threshold_pct: float = DEFAULT_FLAT_PCT
    # A hand-written bar list, from the older `thresholds: [...]` spelling. Kept verbatim when
    # present: the bars somebody wrote out by hand are not always evenly spaced, and silently
    # regularising them would change their results.
    explicit: tuple[float, ...] = field(default=())

    def bars(self) -> list[float]:
        """The bars this rule applies, lowest (rarest band) first."""
        if self.explicit:
            return list(self.explicit)
        return spread(self.low, self.high, self.bins)

    def thresholds(self, freq: pd.Series) -> pd.Series:
        """item -> the bar it has to clear, given how often each item comes up."""
        if self.method == FLAT:
            return flat_thresholds(freq, self.threshold_pct)
        if self.method == FREQ_WIDTH:
            return freq_width_thresholds(freq, self.bars())
        if self.method == EQUAL_COUNT:
            return equal_count_thresholds(freq, self.bars())
        raise ToolkitError(f"Unknown rollup method {self.method!r}; expected one of "
                           f"{', '.join(METHODS)}.")

    def describe(self, items: str = TOPICS) -> str:
        """One line naming the rule, for a run's own summary."""
        if self.method == FLAT:
            return f"one bar of {number(self.threshold_pct)}% for every {SINGULAR[items]}"
        word = "equal-count bins" if self.method == EQUAL_COUNT else "rarity bins"
        bars = self.bars()
        return (f"{word}: {len(bars)} bands from {number(bars[0])}% to {number(bars[-1])}%"
                + (" (bars written out by hand)" if self.explicit else ""))

    def as_config(self) -> dict:
        """What to write into config.yaml for this rule."""
        if self.method == FLAT:
            return {"method": FLAT, "threshold_pct": number(self.threshold_pct)}
        return {"method": self.method, "bins": int(self.bins),
                "range": [number(self.low), number(self.high)]}


DEFAULT = Rollup()


def number(value: float):
    """A percentage as the shortest thing that means it: 30 rather than 30.0, 12.5 as itself."""
    number_ = float(value)
    return int(number_) if number_.is_integer() else round(number_, 4)


def spread(low: float, high: float, bins: int) -> list[float]:
    """`bins` evenly spaced bars from low to high, inclusive of both ends."""
    if bins < 1:
        raise ToolkitError(f"A rollup needs at least one band, not {bins}.")
    if bins == 1:
        return [number(low)]
    step = (float(high) - float(low)) / (bins - 1)
    return [number(float(low) + i * step) for i in range(bins)]


def freq_width_thresholds(freq: pd.Series, thresholds) -> pd.Series:
    """Equal-WIDTH frequency bands: item -> bar. `thresholds` is the bar list, rarest first."""
    thr = sorted(float(t) for t in thresholds)
    bins = pd.cut(freq, bins=len(thr), labels=False, include_lowest=True)   # 0..k-1, 0 = rarest
    return bins.map(lambda b: float(thr[int(b)]))


def equal_count_thresholds(freq: pd.Series, thresholds) -> pd.Series:
    """Equal-COUNT bands: the items are split into groups of (near-)equal size by frequency rank,
    rarest group -> lowest bar. Ties break by first occurrence, so two items that come up equally
    often can land in different groups — the reason freq-width is the recommended method.

    A list shorter than the bar list gets one group per item, over bars spread across the range:
    an eight-topic list compared at nine bands is an ordinary thing to ask for.
    """
    thr = sorted(float(t) for t in thresholds)
    if freq.empty:
        return pd.Series(dtype=float)
    groups = min(len(thr), len(freq))
    if groups == 1:
        return pd.Series(thr[0], index=freq.index, dtype=float)
    picked = [thr[round(i * (len(thr) - 1) / (groups - 1))] for i in range(groups)]
    bands = pd.qcut(freq.rank(method="first"), q=groups, labels=False)
    return bands.map(lambda b: picked[int(b)]).astype(float)


def flat_thresholds(freq: pd.Series, threshold_pct: float) -> pd.Series:
    return pd.Series(float(threshold_pct), index=freq.index)


# --- reading it out of config ----------------------------------------------------------------

def parse(raw, where: str) -> Rollup:
    """The rollup rule config states, or the default when it states none.

    Accepts the older spelling as well (`scheme: flat|binned` with a `thresholds:` bar list),
    because projects made before the methods existed are still in use.
    """
    if raw is None or raw == {}:
        return DEFAULT
    if not isinstance(raw, dict):
        raise ToolkitError(f"{where} must be a mapping, e.g. "
                           f"{{ method: {RECOMMENDED}, bins: {DEFAULT_BINS}, range: [10, 30] }}.")

    method = raw.get("method") or _from_scheme(raw.get("scheme"), where)
    if method is None:
        method = RECOMMENDED
    if method not in METHODS:
        raise ToolkitError(f"{where}: unknown method {method!r}; expected one of "
                           f"{', '.join(METHODS)}.")

    if method == FLAT:
        pct = raw.get("threshold_pct", DEFAULT_FLAT_PCT)
        return Rollup(method=FLAT, threshold_pct=_percent(pct, f"{where}.threshold_pct"))

    explicit = raw.get("thresholds")
    if explicit:
        bars = [_percent(b, f"{where}.thresholds") for b in explicit]
        return Rollup(method=method, bins=len(bars), low=min(bars), high=max(bars),
                      explicit=tuple(bars))

    low, high = _range(raw.get("range"), where)
    bins = raw.get("bins", DEFAULT_BINS)
    if not isinstance(bins, int) or isinstance(bins, bool) or bins < 1:
        raise ToolkitError(f"{where}.bins must be a whole number of bands, got {bins!r}.")
    return Rollup(method=method, bins=bins, low=low, high=high)


def _from_scheme(scheme, where: str) -> str | None:
    """The older `scheme:` key. `binned` meant what `freq_width` means now."""
    if scheme is None:
        return None
    if scheme == "binned":
        return FREQ_WIDTH
    if scheme == FLAT:
        return FLAT
    raise ToolkitError(f"{where}: unknown scheme {scheme!r}; expected 'flat' or 'binned'. "
                       f"Newer projects say `method:` instead — one of {', '.join(METHODS)}.")


def _range(raw, where: str) -> tuple[float, float]:
    if raw is None:
        return DEFAULT_RANGE
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        raise ToolkitError(f"{where}.range must be two percentages, [lowest, highest].")
    low, high = (_percent(v, f"{where}.range") for v in raw)
    if high <= low:
        raise ToolkitError(f"{where}.range: the highest bar ({number(high)}%) must be above the "
                           f"lowest ({number(low)}%).")
    return low, high


def _percent(value, where: str) -> float:
    try:
        pct = float(value)
    except (TypeError, ValueError) as e:
        raise ToolkitError(f"{where}: {value!r} is not a percentage.") from e
    if not 0 < pct <= 100:
        raise ToolkitError(f"{where}: {number(pct)} is not a share of an interview's clips "
                           f"(it has to be above 0 and at most 100).")
    return pct


# --- what the decision aid compares -----------------------------------------------------------

def compare_options(cfg: dict) -> dict:
    """Which variants `toolkit ... thresholds` draws: bin counts, ranges, and flat bars.

    From the step's advanced config (`compare:`), falling back to the shipped defaults so a
    project made before this existed still gets a full comparison.
    """
    said = (cfg or {}).get("compare") or {}
    bins = [int(b) for b in (said.get("bins") or COMPARE_BINS)]
    ranges = [_range(r, "compare.ranges") for r in (said.get("ranges") or COMPARE_RANGES)]
    flat = [_percent(f, "compare.flat") for f in (said.get("flat") or COMPARE_FLAT)]
    return {"bins": bins, "ranges": ranges, "flat": flat}


def compare_text(options: dict) -> dict[str, str]:
    """The same options written the way the flags take them, so the app can show what the aid
    would do and let it be edited in place."""
    return {"bins": ",".join(str(int(b)) for b in options["bins"]),
            "ranges": ",".join(f"{number(lo)}-{number(hi)}" for lo, hi in options["ranges"]),
            "flat": ",".join(str(number(f)) for f in options["flat"])}


def parse_bins(text: str) -> list[int]:
    """`--bins 5,9`."""
    out = []
    for part in _parts(text):
        try:
            out.append(int(part))
        except ValueError as e:
            raise ToolkitError(f"--bins: {part!r} is not a whole number of bands.") from e
    if not out:
        raise ToolkitError("--bins needs at least one number of bands, e.g. --bins 5,9")
    return out


def parse_ranges(text: str) -> list[tuple[float, float]]:
    """`--ranges 10-30,20-40`."""
    out = []
    for part in _parts(text):
        halves = part.split("-")
        if len(halves) != 2:
            raise ToolkitError(f"--ranges: {part!r} is not a range; write it as 10-30.")
        out.append(_range([h.strip() for h in halves], "--ranges"))
    if not out:
        raise ToolkitError("--ranges needs at least one range, e.g. --ranges 10-30,20-40")
    return out


def parse_flat(text: str) -> list[float]:
    """`--flat 20,30,40`."""
    out = [_percent(p, "--flat") for p in _parts(text)]
    if not out:
        raise ToolkitError("--flat needs at least one bar, e.g. --flat 20,30,40")
    return out


def _parts(text: str) -> list[str]:
    return [p.strip() for p in str(text).split(",") if p.strip()]
