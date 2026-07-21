"""Per-interview annotated review mds for `toolkit clip` — clip boundaries in transcript order.

Each clip is a section header, then each paragraph as `**[idx]** [HH:MM:SS] [role] text`.
Procedural paragraphs appear in their own in-place sections so the document reads in
transcript order. `run_clip` writes these for the interviews it just processed;
`annotate_clips` re-renders every interview from the deliverables.
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
    ts = effective_ts(r)
    return f"**[{int(r.paragraph_idx)}]** `[{ts}]` {marker} {r.speech}"


def render_annotated(interview_id: str, paragraphs: pd.DataFrame, clips: pd.DataFrame) -> str:
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
    clip_number_lookup = {c.clip_id: i for i, c in enumerate(clips.itertuples(), start=1)}

    # Walk paragraphs in order; group consecutive rows by their clip_id so each
    # clip OR procedural run becomes one block in document order.
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

        if cid == "procedural":
            label = f"paragraphs {start_idx}" if start_idx == end_idx else f"paragraphs {start_idx}–{end_idx}"
            out.append(f"## Procedural — {label} · {len(block)} paragraph(s) · {words} words")
            out.append("")
            for r in block:
                out.append(render_paragraph(r))
                out.append("")
        elif cid is None:
            label = f"paragraphs {start_idx}" if start_idx == end_idx else f"paragraphs {start_idx}–{end_idx}"
            out.append(f"## Unassigned — {label} · {len(block)} paragraph(s)")
            out.append("")
            for r in block:
                out.append(render_paragraph(r))
                out.append("")
        else:
            c = clip_lookup[cid]
            n = clip_number_lookup[cid]
            dur = ""
            if c.duration_seconds is not None and not pd.isna(c.duration_seconds):
                dur = f" · {c.duration_seconds / 60:.1f} min"
            out.append(
                f"## Clip {n} — paragraphs {start_idx}–{end_idx} · "
                f"{len(block)} paragraph(s) · {words} words{dur}"
            )
            out.append("")
            for r in block:
                out.append(render_paragraph(r))
                out.append("")

        out.append("---")
        out.append("")
        i = j

    return "\n".join(out).rstrip() + "\n"


def write_annotated(project: Project, interview_ids: list[str],
                    paras_df: pd.DataFrame, clips_df: pd.DataFrame) -> Path:
    """Write diags/clip/{interview_id}.md for each interview; returns the diag directory."""
    diag_dir = project.diags_dir / "clip"
    diag_dir.mkdir(parents=True, exist_ok=True)
    for iid in interview_ids:
        md = render_annotated(iid, paras_df[paras_df["interview_id"] == iid],
                              clips_df[clips_df["interview_id"] == iid])
        (diag_dir / f"{iid}.md").write_text(md)
    return diag_dir


def annotate_clips(project: Project) -> None:
    """Re-render every interview's annotated md from the clip deliverables."""
    out_dir = project.outputs_dir / "clips"
    clips_path = out_dir / "clips.parquet"
    paras_path = out_dir / "paragraphs_clipped.parquet"
    for path in (clips_path, paras_path):
        if not path.exists():
            raise ToolkitError(f"{path} not found. Run `toolkit clip` first.")
    clips_df = pd.read_parquet(clips_path)
    paras_df = pd.read_parquet(paras_path)
    ids = sorted(clips_df["interview_id"].unique())
    diag_dir = write_annotated(project, ids, paras_df, clips_df)
    print(f"Wrote {len(ids)} annotated interview(s) -> {diag_dir}")
