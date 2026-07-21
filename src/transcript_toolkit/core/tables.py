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


def load_clips(project: Project) -> pd.DataFrame:
    path = clips_path(project)
    if not path.exists():
        raise ToolkitError(f"{path} not found. Run `toolkit clip` first.")
    return pd.read_parquet(path)


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
