"""`toolkit locations thresholds` — compare clip->interview rollover schemes (decision aid).

Prints per-scheme totals for three candidate rollovers on the mapped clip tags:
  hybrid        — what `toolkit locations rollup` ships: direct+place labels and regions rolled
                  over separately, interview region-tags mapped down to countries and unioned;
  direct-only   — freq-width bins on direct+place labels alone (drops the region info);
  filter-recipe — freq-width bins on the FINAL label set (region fan-out spreads one region tag's
                  clip share over every country in it).
Writes one comparison figure to diags/locations/plots/ when matplotlib is available. No deliverables.
"""
from __future__ import annotations

import pandas as pd

from ...core.config import load_step_config, require
from ...core.ids import narrator_key
from ...core.thresholds import freq_width_thresholds
from ...errors import ToolkitError
from ...project import Project
from .map import load_region_map
from .rollup import rollover

STEP = "locations"


def _pairs(tag: pd.DataFrame) -> set[tuple[str, str]]:
    return {(k, c) for k, row in tag.iterrows() for c in tag.columns[row.values]}


def run_locations_thresholds(project: Project) -> None:
    cfg = load_step_config(project, STEP)
    require(cfg, ["rollup", "region_map_file"], STEP)
    bars = list((cfg["rollup"] or {}).get("thresholds") or [])
    if not bars:
        raise ToolkitError("locations.rollup.thresholds is missing or empty (config.yaml).")
    session_regex = load_step_config(project, "import")["session_regex"]
    region_map = load_region_map(project.root / cfg["region_map_file"])
    relabel = dict(cfg.get("relabel") or {})

    out_dir = project.outputs_dir / "locations"
    cw_path = out_dir / "clip_countries.parquet"
    if not cw_path.exists():
        raise ToolkitError(f"{cw_path} not found. Run `toolkit locations map` first.")
    cw = pd.read_parquet(cw_path)
    cl = pd.read_parquet(out_dir / "clip_countries_long.parquet")

    key = lambda i: narrator_key(i, session_regex)  # noqa: E731
    cw["interview_key"] = cw["interview_id"].map(key)
    cl["interview_key"] = cl["interview_id"].map(key)
    n_clips = cw.groupby("interview_key").size()
    final = cl.rename(columns={"country": "label"})
    direct = final[final["via"].str.split("|")
                   .map(lambda v: "direct" in v or "place" in v).astype(bool)]

    f_tag, _, _ = rollover(final, "label", n_clips, bars)
    d_tag, _, _ = rollover(direct, "label", n_clips, bars)
    # hybrid = direct rollover ∪ interview region-tags mapped down to countries
    regs = (cw[cw["regions"] != ""].assign(region=lambda d: d["regions"].str.split("|"))
            .explode("region")[["interview_key", "region", "clip_id"]])
    r_tag, _, _ = rollover(regs, "region", n_clips, bars)
    hybrid_pairs = set(_pairs(d_tag))
    for k, region in _pairs(r_tag):
        hybrid_pairs |= {(k, relabel.get(c, c)) for c in region_map.get(region, [])}

    d_pct = rollover(direct, "label", n_clips, bars)[1]
    schemes = {"hybrid (shipped)": hybrid_pairs,
               "direct-only": _pairs(d_tag),
               "filter-recipe (final labels)": _pairs(f_tag)}
    print(f"{len(n_clips)} interviews · {len(cw)} clips · bars {sorted(bars)} (freq-width bins)\n")
    for name, pairs in schemes.items():
        labels_reached = {c for _, c in pairs}
        untagged = len(n_clips) - len({k for k, _ in pairs})
        no_direct = sum(1 for k, c in pairs
                        if c not in d_pct.columns or d_pct.at[k, c] == 0)
        print(f"  {name:32} total tags {len(pairs):4} | labels reached {len(labels_reached):3} | "
              f"untagged interviews {untagged} | tags w/o direct evidence "
              f"{no_direct} ({100 * no_direct / max(len(pairs), 1):.0f}%)")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("\nmatplotlib not installed; skipping the comparison figure.")
        return
    freq = final.groupby("label")["clip_id"].nunique()
    order = sorted(freq.index, key=lambda t: (int(freq[t]), t))
    fig, axes = plt.subplots(1, len(schemes), figsize=(4.5 * len(schemes), max(6, 0.28 * len(order))),
                             sharey=True, squeeze=False)
    y = range(len(order))
    for ax, (name, pairs) in zip(axes[0], schemes.items()):
        reach = pd.Series(0, index=order, dtype=int)
        for _, c in pairs:
            if c in reach.index:
                reach[c] += 1
        ax.barh(list(y), reach.values, color="#3b6ea5", edgecolor="white")
        ax.set_title(f"{name}\n{int((reach > 0).sum())}/{len(order)} labels · "
                     f"{len(pairs)} tags", fontsize=9)
        ax.set_xlabel("# interviews tagged", fontsize=8)
        ax.spines[["top", "right"]].set_visible(False)
    axes[0][0].set_yticks(list(y))
    axes[0][0].set_yticklabels([f"{t}  ({int(freq[t])})" for t in order], fontsize=6)
    fig.suptitle("locations: interviews reached per label, by rollover scheme "
                 "(labels sorted by clip-frequency)", fontsize=11)
    plot_dir = project.diags_dir / "locations" / "plots"
    plot_dir.mkdir(parents=True, exist_ok=True)
    out_path = plot_dir / "rollup_schemes.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"\nWrote {out_path}")
