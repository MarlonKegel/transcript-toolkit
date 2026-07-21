"""`toolkit locations map` — map region tags down to countries; build each clip's FINAL label set.

Final labels per clip = the union of (a) direct country tags, (b) the region tags expanded via
the workspace's locations/region_to_country.csv, and (c) subnational place-tags (config
locations.place_tags, e.g. Chechnya/Crimea — tagged in their own right whenever the tagger
extracted them as a raw place; the aggregated country tag is kept alongside). Every label passes
through the canonical relabel map (config locations.relabel), which fixes spellings and merges
labels. Regions are RETAINED in all outputs, with per-label `via` provenance (direct / region
name / place) so every final tag is auditable. A region may map to no countries (the mapping's
explicit `NONE` marker, e.g. Polynesia): its region tag is kept but contributes nothing.

Fail-loud: every region tagged in the corpus must appear in the mapping file.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

from ...core.config import load_step_config, require
from ...core.tables import write_deliverable
from ...errors import ToolkitError
from ...project import Project

STEP = "locations"


def load_region_map(path: Path) -> dict[str, list[str]]:
    """{region -> [country, ...]}; a region whose only row is the explicit 'NONE' marker maps to []."""
    if not path.exists():
        raise ToolkitError(f"Region mapping not found: {path} (advanced key region_map_file).")
    mapping: dict[str, list[str]] = {}
    with path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != ["region", "country"]:
            raise ToolkitError(f"{path.name}: expected header 'region,country', got {reader.fieldnames}")
        for row in reader:
            region, country = row["region"].strip(), row["country"].strip()
            if not region or not country:
                raise ToolkitError(f"{path.name}: blank cell in row {row}")
            mapping.setdefault(region, [])
            if country != "NONE":
                mapping[region].append(country)
    return mapping


def check_regions_known(tagged_regions: set[str], region_map: dict, map_file: str) -> None:
    unknown = sorted(tagged_regions - set(region_map))
    if unknown:
        raise ToolkitError(f"Tagged region(s) missing from {map_file}: {unknown}. "
                           f"Add them to the mapping (use NONE for regions with no countries).")


def run_locations_map(project: Project) -> pd.DataFrame:
    cfg = load_step_config(project, STEP)
    require(cfg, ["region_map_file"], STEP)
    region_map = load_region_map(project.root / cfg["region_map_file"])
    relabel = dict(cfg.get("relabel") or {})
    place_tags = list(cfg.get("place_tags") or [])

    out_dir = project.outputs_dir / "locations"
    loc_path = out_dir / "clip_locations.parquet"
    if not loc_path.exists():
        raise ToolkitError(f"{loc_path} not found. Run `toolkit locations tag` first.")
    wide = pd.read_parquet(loc_path)
    places = pd.read_parquet(out_dir / "clip_locations_long.parquet")

    # clip_id -> canonical place-tag labels for raw places extracted verbatim (Chechnya, Crimea, ...)
    canon_place = {p.casefold(): p for p in place_tags}
    ptag = (places.assign(label=places["place"].str.strip().str.casefold().map(canon_place))
                  .dropna(subset=["label"]).groupby("clip_id")["label"].agg(lambda s: sorted(set(s))))

    check_regions_known({r for rs in wide["regions"] for r in rs.split("|") if r},
                        region_map, cfg["region_map_file"])

    # --- per clip: union direct countries, region expansions and place-tags, case-insensitive ----
    # every label passes through the canonical relabel map first, so variants dedup and merge here
    final_col, from_regions_col, long_rows = [], [], []
    for row in wide.itertuples():
        sources: dict[str, tuple[str, list[str]]] = {}      # casefold -> (display, [via, ...])
        for c in (relabel.get(c, c) for c in row.countries.split("|") if c):
            if c.casefold() not in sources:                  # a merged relabel (Israel+Palestine) dedups here
                sources[c.casefold()] = (c, ["direct"])
        mapped = []
        for region in (r for r in row.regions.split("|") if r):
            for c in (relabel.get(c, c) for c in region_map[region]):
                k = c.casefold()
                if k in sources:
                    display, via = sources[k]
                    sources[k] = (display, via + [region])
                else:
                    sources[k] = (c, [region])
                if c not in mapped:
                    mapped.append(c)
        for p in ptag.get(row.clip_id, []):                  # subnational place-tags (Chechnya, Crimea)
            k = p.casefold()
            if k in sources:
                display, via = sources[k]
                sources[k] = (display, via + ["place"])
            else:
                sources[k] = (p, ["place"])
        finals = [v[0] for v in sources.values()]
        final_col.append("|".join(finals))
        from_regions_col.append("|".join(mapped))
        for display, via in sources.values():
            long_rows.append({"interview_id": row.interview_id, "clip_id": row.clip_id,
                              "country": display, "via": "|".join(via)})

    wide["countries_from_regions"] = from_regions_col
    wide["countries_final"] = final_col
    wide["n_countries_final"] = [len([c for c in s.split("|") if c]) for s in final_col]
    wide["has_country"] = wide["n_countries_final"] > 0
    long = pd.DataFrame(long_rows, columns=["interview_id", "clip_id", "country", "via"])

    write_deliverable(wide, out_dir / "clip_countries.parquet",
                      sort_by=["interview_id", "start_paragraph_idx"])
    write_deliverable(long, out_dir / "clip_countries_long.parquet",
                      sort_by=["interview_id", "clip_id", "country"])
    print(f"Wrote {len(wide)} clips -> {out_dir / 'clip_countries.parquet'}")
    print(f"      {len(long)} (clip, country) rows -> {out_dir / 'clip_countries_long.parquet'}")

    n = len(wide)
    n_direct = int((wide["n_countries"] > 0).sum())
    n_final = int(wide["has_country"].sum())
    only_region = int(((wide["n_countries"] == 0) & (wide["n_countries_final"] > 0)).sum())
    print(f"\n=== {n} clips ===")
    print(f"  >=1 direct country: {n_direct}  |  >=1 FINAL country: {n_final} "
          f"(+{only_region} clips gained countries only via regions)")
    none_used = sorted({r for rs in wide["regions"] for r in rs.split("|") if r and not region_map[r]})
    if none_used:
        print(f"  NONE-mapped regions encountered (retained, no countries): {none_used}")
    print("Next: `toolkit locations rollup`.")
    return wide
