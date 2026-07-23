"""Per-interview annotated review pages for `toolkit clip` — clip boundaries in transcript order.

Each clip is a section, then each paragraph as `[idx] [ts] [role] text`. Procedural paragraphs
appear in their own in-place sections so the document reads in transcript order. `run_clip` writes
these (self-contained HTML, openable in any browser) for the interviews it just processed, plus an
`index.html` linking them; `annotate_clips` re-renders every interview from the deliverables.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ...core.reviewdoc import document, effective_ts, esc, para, write_index
from ...errors import ToolkitError
from ...project import Project


def render_annotated(interview_id: str, paragraphs: pd.DataFrame, clips: pd.DataFrame) -> str:
    paragraphs = paragraphs.sort_values("paragraph_idx").reset_index(drop=True)
    # Normalize missing clip_id to None so runs group cleanly (NaN/pd.NA break `==` grouping).
    paragraphs = paragraphs.assign(clip_id=[None if pd.isna(c) else c for c in paragraphs["clip_id"]])
    clips = clips.sort_values("start_paragraph_idx").reset_index(drop=True)

    n_proc = int((paragraphs["clip_id"] == "procedural").sum())
    n_in_clip = int(paragraphs["clip_id"].notna().sum()) - n_proc
    subtitle = (f"<b>{len(clips)}</b> clips · <b>{len(paragraphs)}</b> paragraphs · "
                f"{n_in_clip} in clips · {n_proc} procedural · "
                f"{int(paragraphs['word_count'].sum())} words")

    clip_lookup = {c.clip_id: c for c in clips.itertuples()}
    clip_number_lookup = {c.clip_id: i for i, c in enumerate(clips.itertuples(), start=1)}

    body: list[str] = []
    # Walk paragraphs in order; group consecutive rows by their clip_id so each
    # clip OR procedural run becomes one section in document order.
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
        span = f"paragraph {start_idx}" if start_idx == end_idx else f"paragraphs {start_idx}–{end_idx}"

        if cid == "procedural":
            cls = "proc"
            h2 = esc(f"Procedural — {span} · {len(block)} paragraph(s) · {words} words")
        elif cid is None:
            cls = "unassigned"
            h2 = esc(f"Unassigned — {span} · {len(block)} paragraph(s)")
        else:
            c = clip_lookup[cid]
            n = clip_number_lookup[cid]
            dur = ""
            if c.duration_seconds is not None and not pd.isna(c.duration_seconds):
                dur = f" · {c.duration_seconds / 60:.1f} min"
            cls = "clip"
            h2 = (f"Clip {n} <span class=\"meta\">{esc(span)} · {len(block)} paragraph(s) · "
                  f"{words} words{esc(dur)}</span>")

        body.append(f'<section class="{cls}">')
        body.append(f"<h2>{h2}</h2>")
        body.extend(para(int(r.paragraph_idx), effective_ts(r), r.speaker_role, r.speech) for r in block)
        body.append("</section>")
        i = j

    return document(interview_id, "\n".join(body), subtitle=subtitle)


def write_annotated(project: Project, interview_ids: list[str],
                    paras_df: pd.DataFrame, clips_df: pd.DataFrame) -> Path:
    """Write diags/clip/{interview_id}.html for each interview + an index.html; returns the dir."""
    diag_dir = project.diags_dir / "clip"
    diag_dir.mkdir(parents=True, exist_ok=True)
    for iid in interview_ids:
        html = render_annotated(iid, paras_df[paras_df["interview_id"] == iid],
                                clips_df[clips_df["interview_id"] == iid])
        (diag_dir / f"{iid}.html").write_text(html)
    _write_index(diag_dir, clips_df)
    return diag_dir


def _write_index(diag_dir: Path, clips_df: pd.DataFrame) -> None:
    """index.html listing every {iid}.html present in the dir, with its clip count."""
    counts = (clips_df.groupby("interview_id").size().to_dict()
              if "interview_id" in clips_df.columns else {})
    entries = [(p.name, p.stem, f"{counts.get(p.stem, '?')} clips")
               for p in sorted(diag_dir.glob("*.html")) if p.name != "index.html"]
    write_index(diag_dir / "index.html", "Clips — review", entries)


def annotate_clips(project: Project) -> None:
    """Re-render every interview's annotated page from the clip deliverables."""
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
    print(f"Wrote {len(ids)} annotated interview(s) -> {diag_dir}/index.html")
