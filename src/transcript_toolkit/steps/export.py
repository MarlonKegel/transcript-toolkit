"""`toolkit export` — one xlsx of everything produced so far.

Reads the deliverables under outputs/ and writes outputs/export.xlsx with three tabs:
- Clips: one row per clip (id, interview, session, start/end, label, per-topic-set tags,
  locations, regions);
- Interviews: one row per narrator (sessions, summary, per-topic-set tags, locations);
- Categories: the vocabularies (each topic set's names, the location labels) as reference columns.

Incremental: a column appears only if its step has run; missing steps are announced, not fatal.
Overwrites the file each run (idempotent). No live Google Sheets — this produces a plain xlsx
you can open in Excel or upload to Google Sheets.
"""
from __future__ import annotations

import pandas as pd
from openpyxl import Workbook
from openpyxl.utils import get_column_letter

from ..core.config import load_root_config, load_step_config
from ..core.ids import narrator_key
from ..errors import ToolkitError
from ..project import Project
from .topics.taxonomy import load_topic_set


def _read(path):
    return pd.read_parquet(path) if path.exists() else None


def _topic_sets(project: Project) -> list[str]:
    topics = (load_root_config(project).get("topics") or {})
    return list((topics.get("sets") or {}).keys())


def _clip_topic_tags(project: Project, set_name: str) -> dict[str, str] | None:
    """clip_id -> comma-joined names of that set's assigned (score==max) topics."""
    long = _read(project.outputs_dir / "topics" / f"{set_name}_clip_topics_long.parquet")
    if long is None:
        return None
    top = long["score"].max() if len(long) else 0
    assigned = long[long["score"] == top]
    return {cid: ", ".join(sorted(g["topic_name"])) for cid, g in assigned.groupby("clip_id")}


def build_clips_sheet(project: Project, sets: list[str]) -> tuple[pd.DataFrame, list[str]]:
    labels = _read(project.outputs_dir / "labels" / "labels.parquet")
    clips = labels if labels is not None else _read(project.outputs_dir / "clips" / "clips.parquet")
    if clips is None:
        raise ToolkitError("No clips yet — run `toolkit clip` first (export needs at least clips).")

    session_regex = load_step_config(project, "import")["session_regex"]
    df = pd.DataFrame({
        "Clip Id": clips["clip_id"],
        "Interview": clips["interview_id"].map(lambda i: narrator_key(i, session_regex)),
        "Session": clips["interview_id"],
        "Start": clips["start_ts"],
        "End": clips["end_ts"],
    })
    included = ["clips"]
    if labels is not None:
        df["Label"] = clips["label"]
        included.append("labels")

    for set_name in sets:
        tags = _clip_topic_tags(project, set_name)
        if tags is not None:
            df[f"Topics: {set_name}"] = df["Clip Id"].map(tags).fillna("")
            included.append(f"topics:{set_name}")

    countries = _read(project.outputs_dir / "locations" / "clip_countries.parquet")
    if countries is not None:
        cmap = dict(zip(countries["clip_id"], countries["countries_final"].str.replace("|", ", ")))
        rmap = dict(zip(countries["clip_id"], countries["regions"].str.replace("|", ", ")))
        df["Locations"] = df["Clip Id"].map(cmap).fillna("")
        df["Regions"] = df["Clip Id"].map(rmap).fillna("")
        included.append("locations")
    return df, included


def build_interviews_sheet(project: Project, sets: list[str]) -> pd.DataFrame | None:
    session_regex = load_step_config(project, "import")["session_regex"]
    frames: dict[str, dict] = {}

    def row(key: str) -> dict:
        return frames.setdefault(key, {"Interview": key})

    summaries = _read(project.outputs_dir / "summaries" / "summaries.parquet")
    if summaries is not None:
        for r in summaries.itertuples():
            rr = row(r.interview_key)
            rr["Sessions"] = str(r.session_ids).replace("|", ", ")
            rr["Summary"] = r.summary

    for set_name in sets:
        wide = _read(project.outputs_dir / "topics" / f"{set_name}_interview_topics_wide.parquet")
        if wide is not None:
            for r in wide.itertuples():
                row(r.interview_key)[f"Topics: {set_name}"] = str(r.topics).replace("|", ", ")

    loc = _read(project.outputs_dir / "locations" / "interview_locations_wide.parquet")
    if loc is not None:
        for r in loc.itertuples():
            row(r.interview_key)["Locations"] = str(r.labels).replace("|", ", ")

    if not frames:
        return None
    # a Session column derived from clips if summaries didn't populate one
    df = pd.DataFrame(list(frames.values()))
    return df.sort_values("Interview").reset_index(drop=True)


def build_categories_sheet(project: Project, sets: list[str]) -> pd.DataFrame:
    cfg = load_root_config(project)
    columns: dict[str, list[str]] = {}
    for set_name in sets:
        try:
            ts = load_topic_set(project, load_step_config(project, "topics"), set_name)
            columns[f"Topics: {set_name}"] = [t["name"] for t in ts.topics]
        except ToolkitError:
            continue
    regions_file = load_step_config(project, "locations").get("regions_file")
    if regions_file:
        path = project.root / regions_file
        if path.exists():
            import yaml
            regions = yaml.safe_load(path.read_text()) or []
            columns["Regions"] = list(regions)
    countries = _read(project.outputs_dir / "locations" / "clip_countries_long.parquet")
    if countries is not None and len(countries):
        columns["Locations"] = sorted(countries["country"].unique())
    if not columns:
        return pd.DataFrame()
    width = max(len(v) for v in columns.values())
    return pd.DataFrame({k: v + [""] * (width - len(v)) for k, v in columns.items()})


def _write_sheet(wb: Workbook, title: str, df: pd.DataFrame) -> None:
    ws = wb.create_sheet(title)
    ws.append(list(df.columns))
    for _, r in df.iterrows():
        ws.append(["" if pd.isna(v) else v for v in r.tolist()])
    for i, col in enumerate(df.columns, start=1):
        longest = max([len(str(col))] + [len(str(v)) for v in df[col].tolist()[:200]], default=10)
        ws.column_dimensions[get_column_letter(i)].width = min(max(longest + 2, 10), 60)


def run_export(project: Project, out: str | None = None) -> None:
    cfg = load_step_config(project, "export")
    sets = _topic_sets(project)

    clips_df, included = build_clips_sheet(project, sets)
    interviews_df = build_interviews_sheet(project, sets)
    categories_df = build_categories_sheet(project, sets)

    wb = Workbook()
    wb.remove(wb.active)
    tabs = cfg.get("tabs") or {}
    _write_sheet(wb, tabs.get("clips", "Clips"), clips_df)
    if interviews_df is not None:
        _write_sheet(wb, tabs.get("interviews", "Interviews"), interviews_df)
    if not categories_df.empty:
        _write_sheet(wb, tabs.get("categories", "Categories"), categories_df)

    out_path = (project.root / out) if out else (project.outputs_dir / cfg.get("filename", "export.xlsx"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)

    print(f"Wrote {out_path}")
    print(f"  Clips tab: {len(clips_df)} clips, columns include: {', '.join(included)}")
    if interviews_df is not None:
        print(f"  Interviews tab: {len(interviews_df)} narrators")
    all_steps = {"clips", "labels", "locations"} | {f"topics:{s}" for s in sets}
    missing = sorted(all_steps - set(included))
    if missing:
        print(f"  Not yet included (step not run): {', '.join(missing)}")
    print("  Note: Excel has no multi-select dropdowns; the Categories tab is a reference list. "
          "After uploading to Google Sheets you re-add validation manually.")
