"""`toolkit locations rollup` — interview-level location tags: the HYBRID clip->interview rollover.

Two rollovers run separately per narrator (sessions pooled via core.ids.narrator_key — no-op-safe
for session-less ids), each with a rarity-binned threshold (config locations.rollup.thresholds,
freq-width bands: the rarest band clears the lowest bar):

  1. DIRECT labels — an interview is tagged a label when the share of its clips carrying that
     label with direct evidence (via includes `direct` or `place`) clears the label's bar.
  2. REGIONS — an interview is tagged a region when the share of its clips tagged that region
     clears the region's bar; the interview's region tags are then mapped down to countries
     (region_to_country.csv + locations.relabel), exactly like the map step does per clip.

Final interview labels = direct ∪ mapped-down regions, with `via` provenance. The region fan-out
therefore only reaches an interview when the REGION ITSELF is interview-substantive — not by
accumulating scattered per-country shares (`toolkit locations thresholds` is the decision aid).
"""
from __future__ import annotations

import pandas as pd

from ...core.config import load_step_config, require
from ...core.ids import narrator_key
from ...core.tables import write_deliverable
from ...core.thresholds import freq_width_thresholds
from ...errors import ToolkitError
from ...project import Project
from .map import check_regions_known, load_region_map

STEP = "locations"


def rollover(long: pd.DataFrame, key_col: str, n_clips: pd.Series, bars
             ) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    """Generic rarity-binned rollover: (tagged bool frame, pct frame, per-item threshold Series).
    `long` = one row per (interview_key, <key_col>, clip_id)."""
    if long.empty:                                       # no items at all -> nothing to tag
        empty = pd.DataFrame(index=n_clips.index)
        return empty.astype(bool), empty, pd.Series(dtype=float)
    counts = long.groupby(["interview_key", key_col])["clip_id"].nunique().unstack(fill_value=0)
    counts = counts.reindex(n_clips.index, fill_value=0)
    pct = counts.div(n_clips, axis=0) * 100
    thr = freq_width_thresholds(long.groupby(key_col)["clip_id"].nunique(), bars)
    return pct.ge(thr, axis=1), pct, thr


def run_locations_rollup(project: Project) -> pd.DataFrame:
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
    check_regions_known({r for rs in cw["regions"] for r in rs.split("|") if r},
                        region_map, cfg["region_map_file"])

    cw["interview_key"] = cw["interview_id"].map(lambda i: narrator_key(i, session_regex))
    n_clips = cw.groupby("interview_key").size()
    n_sessions = cw.groupby("interview_key")["interview_id"].nunique()

    # 1) DIRECT labels: clips whose tag carries direct/place evidence
    # (.astype(bool): on an empty table the mapped mask is dtype object, and pandas would
    # treat a non-bool Series as a column selector, silently dropping every column)
    direct_mask = cl["via"].str.split("|").map(lambda v: "direct" in v or "place" in v).astype(bool)
    direct = cl[direct_mask].copy()
    direct["interview_key"] = direct["interview_id"].map(lambda i: narrator_key(i, session_regex))
    direct = direct.rename(columns={"country": "label"})
    d_tag, d_pct, d_thr = rollover(direct, "label", n_clips, bars)

    # 2) REGIONS, rolled over as regions, then mapped down (relabel applied like the map step)
    regs = (cw[cw["regions"] != ""].assign(region=lambda d: d["regions"].str.split("|"))
            .explode("region")[["interview_key", "region", "clip_id"]])
    r_tag, r_pct, r_thr = rollover(regs, "region", n_clips, bars)

    # 3) union with provenance
    long_rows, wide_rows = [], []
    for k in n_clips.index:
        sources: dict[str, tuple[str, list[str]]] = {}       # casefold -> (display, [via, ...])
        for lab in d_tag.columns[d_tag.loc[k]]:
            sources[lab.casefold()] = (lab, ["direct"])
        regions_hit = list(r_tag.columns[r_tag.loc[k]])
        for region in regions_hit:
            for c in (relabel.get(c, c) for c in region_map[region]):
                if c.casefold() in sources:
                    disp, via = sources[c.casefold()]
                    sources[c.casefold()] = (disp, via + [region])
                else:
                    sources[c.casefold()] = (c, [region])
        labs = sorted(v[0] for v in sources.values())
        wide_rows.append({"interview_key": k, "n_sessions": int(n_sessions[k]),
                          "n_clips": int(n_clips[k]),
                          "regions": "|".join(sorted(regions_hit)), "n_regions": len(regions_hit),
                          "labels": "|".join(labs), "n_labels": len(labs)})
        for disp, via in sources.values():
            has_direct = disp in d_pct.columns
            long_rows.append({
                "interview_key": k, "label": disp, "via": "|".join(via),
                "n_clips_direct": int(round(d_pct.at[k, disp] * n_clips[k] / 100)) if has_direct else 0,
                "n_clips_total": int(n_clips[k]),
                "pct_clips_direct": round(float(d_pct.at[k, disp]), 2) if has_direct else 0.0,
                "threshold_pct_direct": float(d_thr[disp]) if has_direct else None,
            })
    wide = pd.DataFrame(wide_rows, columns=["interview_key", "n_sessions", "n_clips", "regions",
                                            "n_regions", "labels", "n_labels"])
    long = pd.DataFrame(long_rows, columns=["interview_key", "label", "via", "n_clips_direct",
                                            "n_clips_total", "pct_clips_direct",
                                            "threshold_pct_direct"])

    # full interview x region audit grid (pct, threshold, tagged)
    if len(r_pct.columns):
        rlong = r_pct.round(2).reset_index().melt("interview_key", var_name="region",
                                                  value_name="pct_clips")
        rlong["threshold_pct"] = rlong["region"].map(r_thr)
        rlong["tagged"] = rlong.apply(lambda r: bool(r_tag.at[r["interview_key"], r["region"]]), axis=1)
        rlong["n_clips_total"] = rlong["interview_key"].map(n_clips)
    else:
        rlong = pd.DataFrame(columns=["interview_key", "region", "pct_clips", "threshold_pct",
                                      "tagged", "n_clips_total"])

    write_deliverable(wide, out_dir / "interview_locations_wide.parquet", sort_by="interview_key")
    write_deliverable(long, out_dir / "interview_locations_long.parquet",
                      sort_by=["interview_key", "label"])
    write_deliverable(rlong, out_dir / "interview_regions_long.parquet",
                      sort_by=["interview_key", "region"])

    n_int = len(wide)
    print(f"Hybrid rollover · thresholds {sorted(bars)} (freq-width bins, both rollovers)")
    print(f"{n_int} interviews ({int(n_sessions.sum())} sessions / {int(n_clips.sum())} clips)")
    nl = wide["n_labels"]
    print(f"labels/interview: mean {nl.mean():.1f}, median {int(nl.median())}, "
          f"range {nl.min()}-{nl.max()}; none: {int((nl == 0).sum())}")
    via_direct = long["via"].str.contains("direct") if len(long) else pd.Series(dtype=bool)
    print(f"final tags: {len(long)} | with direct evidence: {int(via_direct.sum())} | "
          f"region-only: {int((~via_direct).sum())} | interview region-tags: "
          f"{int(wide['n_regions'].sum())}")
    print(f"\nWrote {out_dir}/interview_locations_{{wide,long}}.parquet + "
          f"interview_regions_long.parquet (+csv)")
    return wide
