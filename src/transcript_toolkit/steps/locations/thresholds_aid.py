"""`toolkit locations thresholds` — the decision aid that comes BEFORE `toolkit locations rollup`.

Same shape as the topics one: every candidate rollup rule is worked out against the tags that are
already there, and the answers are drawn side by side — a panel per method, the recommended one
open — so the rule is chosen by looking at what it would do.

Two things are particular to places. First, every rule is run through the whole hybrid rollover
(direct places rolled up as places, regions rolled up as regions and then expanded into their
countries), so the counts are the ones a rollup would actually write. Second, a place that only
ever comes up as part of a region has no bar of its own; the bar shown for it is the region's,
which is the bar it really had to clear.

A last panel compares the hybrid rollover itself against the two simpler ones it was chosen over.
Reads the mapped clip tags only: no deliverables, no API calls.
"""
from __future__ import annotations

import pandas as pd

from ...core import reviewdoc, thresholdreview, thresholds
from ...core.config import load_step_config, require
from ...core.ids import narrator_key
from ...errors import ToolkitError
from ...project import Project
from .map import load_region_map
from .rollup import locations_rollup, rollover

STEP = "locations"

LEAD = ("Every rule below tags an interview with a place once enough of that interview's clips "
        "talk about it. They differ in how 'enough' is decided, and the difference is largest "
        "for the places that come up least. Pick the one whose picture you would be happy to "
        "publish, then set it under 'Choose how tags are decided' and roll up.")

HYBRID_LEAD = (
    "How a region becomes an interview's places, which is a separate question from where the bar "
    "sits. The toolkit ships the first of these. In it, regions are rolled up as regions and only "
    "then expanded into their countries, so a country arrives through a region only when the "
    "region itself is what the interview is about. The alternatives either throw the region "
    "information away, or spread one region's clips across every country in it — which quietly "
    "tags a lot of countries nobody talked about."
)


def _pairs(tag: pd.DataFrame) -> set[tuple[str, str]]:
    return {(k, c) for k, row in tag.iterrows() for c in tag.columns[row.values]}


def run_locations_thresholds(project: Project, bins: list[int] | None = None,
                             ranges: list[tuple[float, float]] | None = None,
                             flat: list[float] | None = None) -> None:
    cfg = load_step_config(project, STEP)
    require(cfg, ["region_map_file"], STEP)
    current = locations_rollup(cfg)
    session_regex = load_step_config(project, "import")["session_regex"]
    region_map = load_region_map(project.root / cfg["region_map_file"])
    relabel = dict(cfg.get("relabel") or {})

    out_dir = project.outputs_dir / STEP
    cw_path = out_dir / "clip_countries.parquet"
    if not cw_path.exists():
        raise ToolkitError(f"{cw_path} not found. Run `toolkit locations map` first.")
    cw = pd.read_parquet(cw_path)
    cl = pd.read_parquet(out_dir / "clip_countries_long.parquet")

    key = lambda i: narrator_key(i, session_regex)  # noqa: E731
    cw["interview_key"] = cw["interview_id"].map(key)
    cl["interview_key"] = cl["interview_id"].map(key)
    n_clips = cw.groupby("interview_key").size()
    n_int = len(n_clips)
    final = cl.rename(columns={"country": "label"})
    direct = final[final["via"].str.split("|")
                   .map(lambda v: "direct" in v or "place" in v).astype(bool)]
    regs = (cw[cw["regions"] != ""].assign(region=lambda d: d["regions"].str.split("|"))
            .explode("region")[["interview_key", "region", "clip_id"]])

    freq = final.groupby("label")["clip_id"].nunique()
    labels = list(freq.index)
    order = sorted(labels, key=lambda t: (int(freq[t]), t))

    def hybrid(rollup: thresholds.Rollup):
        """(interview, place) pairs the shipped rollover would produce under this rule, and the
        bar each place had to clear to be in them."""
        d_tag, _, d_thr = rollover(direct, "label", n_clips, rollup)
        r_tag, _, r_thr = rollover(regs, "region", n_clips, rollup)
        pairs = set(_pairs(d_tag))
        for interview, region in _pairs(r_tag):
            pairs |= {(interview, relabel.get(c, c)) for c in region_map.get(region, [])}
        return pairs, _bar_per_label(labels, d_thr, r_thr, region_map, relabel)

    def evaluate(rollup: thresholds.Rollup):
        pairs, thr = hybrid(rollup)
        reach = pd.Series(0, index=labels, dtype=int)
        for _, label in pairs:
            if label in reach.index:
                reach[label] += 1
        return thr, reach, n_int - len({k for k, _ in pairs})

    options = thresholds.compare_options(cfg)
    for name, given in (("bins", bins), ("ranges", ranges), ("flat", flat)):
        if given:
            options[name] = given

    panels = thresholdreview.build(options, current, evaluate, thresholds.PLACES)
    said = current.describe(thresholds.PLACES)
    print(f"Comparing rollup rules · {n_int} interviews · {len(cw)} clips · {len(labels)} places")
    print(f"What you have now: {said}")
    thresholdreview.report(panels, n_int)

    schemes = _schemes(final, direct, regs, n_clips, current, region_map, relabel)
    _report_schemes(schemes, n_int)
    out = thresholdreview.write(
        project.diags_dir / STEP, "locations",
        title="Locations · choosing how tags are decided",
        subtitle=f"{len(labels)} places · {n_int} interviews · what you have now: {said}",
        panels=panels, order=order, freq=freq, n_int=n_int, lead=LEAD,
        extra=reviewdoc.panel("How regions become an interview's places",
                              _scheme_table(schemes, n_int), lead=HYBRID_LEAD))
    print(f"\nWrote {out}")


def _bar_per_label(labels: list[str], d_thr: pd.Series, r_thr: pd.Series, region_map: dict,
                   relabel: dict) -> pd.Series:
    """The bar each place had to clear: its own where it has one, else the easiest bar among the
    regions that would carry it in."""
    via_region: dict[str, float] = {}
    for region, bar in r_thr.items():
        for country in (relabel.get(c, c) for c in region_map.get(region, [])):
            via_region[country] = min(via_region.get(country, bar), float(bar))
    return pd.Series({label: float(d_thr[label]) if label in d_thr.index
                      else via_region.get(label, float("nan"))
                      for label in labels})


def _schemes(final, direct, regs, n_clips, rollup, region_map, relabel) -> dict[str, set]:
    """The three ways of getting from clip tags to interview places, under the current rule."""
    f_tag, _, _ = rollover(final, "label", n_clips, rollup)
    d_tag, _, _ = rollover(direct, "label", n_clips, rollup)
    r_tag, _, _ = rollover(regs, "region", n_clips, rollup)
    hybrid = set(_pairs(d_tag))
    for interview, region in _pairs(r_tag):
        hybrid |= {(interview, relabel.get(c, c)) for c in region_map.get(region, [])}
    return {"Regions rolled up as regions, then expanded (what the toolkit does)": hybrid,
            "Only places said outright; region information dropped": _pairs(d_tag),
            "Every country a region covers, counted as if said outright": _pairs(f_tag)}


def _scheme_rows(schemes: dict[str, set], n_int: int) -> list[list[str]]:
    return [[name, f"{len({c for _, c in pairs})}", f"{len(pairs)}",
             f"{n_int - len({k for k, _ in pairs})}"]
            for name, pairs in schemes.items()]


def _scheme_table(schemes: dict[str, set], n_int: int) -> str:
    return reviewdoc.table(["Rollover", "Places reached", "Tags in total",
                            f"Interviews with none (of {n_int})"],
                           _scheme_rows(schemes, n_int), numeric={1, 2, 3})


def _report_schemes(schemes: dict[str, set], n_int: int) -> None:
    print("\nHow regions become an interview's places (under the rule you have now)")
    for name, places, tags, none in _scheme_rows(schemes, n_int):
        print(f"  {name}\n    {places} places reached · {tags} tags · {none} of {n_int} "
              f"interviews with none")
