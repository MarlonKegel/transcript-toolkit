"""Hand-edited clip labels: `label_overrides.csv` at the workspace root.

The pipeline's own labels stay pure model output (`outputs/labels/`); a curator's fix lives
here and is laid over the model's label wherever labels are shown or exported. Three ways an
override comes to exist, all landing in this one file: the edit control in a label review
page, editing the Label column of the exported sheet (the next export keeps the difference),
or editing this file by hand.

An override is pinned to the clip's span — its start and end timestamps. Re-running steps
never disturbs it, but when the clip itself changes (a corrected transcript, different clip
boundaries) the pin no longer matches and the override is skipped OUT LOUD rather than
silently applied to different text. A re-imported transcript takes its overrides with it,
the same way it takes the rest of its old results.
"""
from __future__ import annotations

import pandas as pd

from ..errors import ToolkitError
from ..project import Project

COLUMNS = ["clip_id", "label", "start_ts", "end_ts", "replaces"]


def load(project: Project) -> pd.DataFrame:
    path = project.label_overrides_path
    if not path.exists():
        return pd.DataFrame(columns=COLUMNS)
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        raise ToolkitError(f"{path.name} is missing the column(s) {', '.join(missing)} — "
                           f"expected exactly: {', '.join(COLUMNS)}.")
    return df


def save(project: Project, df: pd.DataFrame) -> None:
    df[COLUMNS].sort_values("clip_id").to_csv(project.label_overrides_path, index=False)


def upsert(project: Project, clip_id: str, label: str, clips: pd.DataFrame,
           replaces: str = "") -> None:
    """Record (or update) one hand-written label, pinned to the clip's current span."""
    row = clips[clips["clip_id"] == clip_id]
    if row.empty:
        raise ToolkitError(f"No clip {clip_id!r} to attach a label override to.")
    if not str(label).strip():
        raise ToolkitError("A label cannot be empty.")
    df = load(project)
    existing = df[df["clip_id"] == clip_id]
    if not existing.empty and not replaces:
        replaces = existing.iloc[0]["replaces"]     # keep pointing at the model's own words
    df = df[df["clip_id"] != clip_id]
    df = pd.concat([df, pd.DataFrame([{
        "clip_id": clip_id, "label": str(label).strip(),
        "start_ts": str(row.iloc[0]["start_ts"]), "end_ts": str(row.iloc[0]["end_ts"]),
        "replaces": str(replaces),
    }])], ignore_index=True)
    save(project, df)


def remove(project: Project, clip_id: str) -> bool:
    df = load(project)
    keep = df[df["clip_id"] != clip_id]
    if len(keep) == len(df):
        return False
    save(project, keep)
    return True


def overlay(project: Project, clips: pd.DataFrame) -> tuple[dict[str, str], list[str]]:
    """What to show instead of the model's label, and the complaints for pins that no longer
    match: {clip_id: label}, [reasons]. A skipped override stays in the file — the complaint
    is the invitation to redo or remove it."""
    df = load(project)
    if df.empty:
        return {}, []
    spans = {c.clip_id: (str(c.start_ts), str(c.end_ts)) for c in clips.itertuples()}
    shown: dict[str, str] = {}
    complaints: list[str] = []
    for r in df.itertuples():
        span = spans.get(r.clip_id)
        if span is None:
            complaints.append(f"label override for {r.clip_id} skipped — there is no such clip "
                              f"any more (see {project.label_overrides_path.name})")
        elif span != (str(r.start_ts), str(r.end_ts)):
            complaints.append(f"label override for {r.clip_id} skipped — the clip's span has "
                              f"changed since the edit (see {project.label_overrides_path.name})")
        else:
            shown[r.clip_id] = str(r.label)
    return shown, complaints


def purge_interviews(project: Project, interview_ids) -> bool:
    """A re-imported (or removed) transcript takes its hand-edited labels with it."""
    df = load(project)
    if df.empty:
        return False
    prefixes = tuple(f"{iid}_" for iid in interview_ids)
    keep = df[~df["clip_id"].str.startswith(prefixes)]
    if len(keep) == len(df):
        return False
    save(project, keep)
    return True
