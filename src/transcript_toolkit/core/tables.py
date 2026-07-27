"""Loading and merging the workspace's data tables."""
from __future__ import annotations

import pandas as pd

from ..errors import ToolkitError
from ..project import Project


def load_paragraphs(project: Project) -> pd.DataFrame:
    if not project.paragraphs_path.exists():
        raise ToolkitError(f"{project.paragraphs_path} not found. Run `toolkit import` first.")
    return pd.read_parquet(project.paragraphs_path)


def clips_path(project: Project):
    return project.outputs_dir / "clips" / "clips.parquet"


def paragraphs_clipped_path(project: Project):
    return project.outputs_dir / "clips" / "paragraphs_clipped.parquet"


def load_clips(project: Project, allow_demo: bool = False) -> pd.DataFrame:
    """The clips table. `allow_demo` (set by a downstream step's own --demo run) falls back to
    the clips a `toolkit clip --demo` produced, so each step can be demoed and reviewed in turn
    without first paying for a full clip run of the corpus."""
    return _load_clip_table(project, clips_path(project), "clips.parquet", allow_demo)


def load_paragraphs_clipped(project: Project, allow_demo: bool = False) -> pd.DataFrame:
    return _load_clip_table(project, paragraphs_clipped_path(project),
                            "paragraphs_clipped.parquet", allow_demo)


def _load_clip_table(project: Project, path, filename: str, allow_demo: bool) -> pd.DataFrame:
    if path.exists():
        return pd.read_parquet(path)
    demo_path = project.demo_dir / filename
    if allow_demo and demo_path.exists():
        df = pd.read_parquet(demo_path)
        if filename == "clips.parquet":
            print(f"NOTE: using the {len(df)} clips from your `toolkit clip --demo` run "
                  f"({df['interview_id'].nunique()} interview(s)) — `toolkit clip` has not been "
                  f"run on the full corpus yet. That is fine for a demo; run it before the full "
                  f"run of this step.")
        return df
    hint = ("Run `toolkit clip --demo` first (or `toolkit clip` for the whole corpus)."
            if allow_demo else "Run `toolkit clip` first.")
    raise ToolkitError(f"{path} not found. {hint}")


def write_demo_tables(project: Project, clips: pd.DataFrame, paragraphs: pd.DataFrame) -> None:
    """Persist a clip demo's tables so the next step's demo has something to work from."""
    project.demo_dir.mkdir(parents=True, exist_ok=True)
    clips.to_parquet(project.demo_dir / "clips.parquet", index=False)
    paragraphs.to_parquet(project.demo_dir / "paragraphs_clipped.parquet", index=False)


def paragraphs_by_interview(paragraphs_df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """{interview_id -> paragraph_idx-indexed frame} for clip rendering."""
    return {iid: g.sort_values("paragraph_idx").set_index("paragraph_idx")
            for iid, g in paragraphs_df.groupby("interview_id")}


def merge_subset(existing: pd.DataFrame | None, new: pd.DataFrame, key_col: str) -> pd.DataFrame:
    """Splice a subset run's rows into an existing deliverable: replace rows whose key is in
    `new`, keep the rest. A --demo/--interview run must never clobber a prior full run."""
    if existing is None:
        return new.reset_index(drop=True)
    keep = existing[~existing[key_col].isin(set(new[key_col]))]
    return pd.concat([keep, new], ignore_index=True)


def write_deliverable(df: pd.DataFrame, parquet_path, sort_by: str) -> None:
    df = df.sort_values(sort_by).reset_index(drop=True)
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(parquet_path, index=False)
    df.to_csv(parquet_path.with_suffix(".csv"), index=False)
