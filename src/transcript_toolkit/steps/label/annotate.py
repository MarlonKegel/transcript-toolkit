"""Per-interview annotated review mds for `toolkit label` — clip boundaries WITH their labels.

Mirrors diags/clip/ (clips AND procedural paragraphs in document order), adding a `**Label:**`
line under each clip header. Procedural blocks get no label line (procedural paragraphs are
never labeled). `run_label` writes these for the interviews it just processed;
`annotate_labels` re-renders every labeled interview from the deliverables.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ...errors import ToolkitError
from ...project import Project

ROLE_MARKER = {"Interviewer": "[Q]", "Narrator": "[N]", "Other": "[O]"}


def effective_ts(r) -> str:
    return r.sub_time_start or r.turn_time_start


def render_paragraph(r) -> str:
    marker = ROLE_MARKER.get(r.speaker_role, "[?]")
    return f"**[{int(r.paragraph_idx)}]** `[{effective_ts(r)}]` {marker} {r.speech}"


def render_annotated(interview_id: str, paragraphs: pd.DataFrame, clips: pd.DataFrame,
                     label_by_id: dict[str, str]) -> str:
    paragraphs = paragraphs.sort_values("paragraph_idx").reset_index(drop=True)
    # Normalize missing clip_id to None so runs group cleanly (NaN/pd.NA break `==` grouping).
    paragraphs = paragraphs.assign(clip_id=[None if pd.isna(c) else c for c in paragraphs["clip_id"]])
    clips = clips.sort_values("start_paragraph_idx").reset_index(drop=True)

    n_proc = int((paragraphs["clip_id"] == "procedural").sum())
    n_in_clip = int(paragraphs["clip_id"].notna().sum()) - n_proc
    head = [
        f"# {interview_id}",
        "",
        f"**Clips**: {len(clips)} · **Paragraphs**: {len(paragraphs)} · "
        f"**In clips**: {n_in_clip} · **Procedural**: {n_proc} · "
        f"**Total words**: {int(paragraphs['word_count'].sum())}",
    ]
    out: list[str] = ["\n".join(head), ""]

    clip_lookup = {c.clip_id: c for c in clips.itertuples()}
    clip_number = {c.clip_id: i for i, c in enumerate(clips.itertuples(), start=1)}

    rows = list(paragraphs.itertuples())
    i = 0
    while i < len(rows):
        cid = rows[i].clip_id
        j = i
        while j < len(rows) and rows[j].clip_id == cid:
            j += 1
        block = rows[i:j]
        start_idx = int(block[0].paragraph_idx)
        end_idx = int(block[-1].paragraph_idx)
        words = sum(int(r.word_count) for r in block)
        span = f"paragraphs {start_idx}" if start_idx == end_idx else f"paragraphs {start_idx}–{end_idx}"

        if cid == "procedural":
            out.append(f"## Procedural — {span} · {len(block)} paragraph(s) · {words} words")
            out.append("")
        elif cid is None:
            out.append(f"## Unassigned — {span} · {len(block)} paragraph(s)")
            out.append("")
        else:
            c = clip_lookup[cid]
            n = clip_number[cid]
            dur = ""
            if c.duration_seconds is not None and not pd.isna(c.duration_seconds):
                dur = f" · {c.duration_seconds / 60:.1f} min"
            out.append(f"## Clip {n} — {span} · {len(block)} paragraph(s) · {words} words{dur}")
            out.append("")
            out.append(f"**Label:** {label_by_id.get(cid, '⟨missing⟩')}")
            out.append("")

        for r in block:
            out.append(render_paragraph(r))
            out.append("")
        out.append("---")
        out.append("")
        i = j

    return "\n".join(out).rstrip() + "\n"


def write_annotated(project: Project, interview_ids: list[str], paras_df: pd.DataFrame,
                    clips_df: pd.DataFrame, label_by_id: dict[str, str]) -> Path:
    """Write diags/label/{interview_id}.md for each interview; returns the diag directory."""
    diag_dir = project.diags_dir / "label"
    diag_dir.mkdir(parents=True, exist_ok=True)
    for iid in interview_ids:
        md = render_annotated(iid, paras_df[paras_df["interview_id"] == iid],
                              clips_df[clips_df["interview_id"] == iid], label_by_id)
        (diag_dir / f"{iid}.md").write_text(md)
    return diag_dir


def annotate_labels(project: Project) -> None:
    """Re-render every labeled interview's annotated md from the deliverables."""
    labels_path = project.outputs_dir / "labels" / "labels.parquet"
    if not labels_path.exists():
        raise ToolkitError(f"{labels_path} not found. Run `toolkit label` first.")
    clips_path = project.outputs_dir / "clips" / "clips.parquet"
    paras_path = project.outputs_dir / "clips" / "paragraphs_clipped.parquet"
    for path in (clips_path, paras_path):
        if not path.exists():
            raise ToolkitError(f"{path} not found. Run `toolkit clip` first.")

    labels_df = pd.read_parquet(labels_path)
    clips_df = pd.read_parquet(clips_path)
    paras_df = pd.read_parquet(paras_path)
    label_by_id = dict(zip(labels_df["clip_id"], labels_df["label"]))

    ids = sorted(labels_df["interview_id"].unique())
    diag_dir = write_annotated(project, ids, paras_df, clips_df, label_by_id)
    print(f"Wrote {len(ids)} annotated interview(s) -> {diag_dir}")
