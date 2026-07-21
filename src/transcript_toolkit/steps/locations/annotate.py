"""Annotated review markdown for clip location tags (diags/locations/).

`write_review_md` renders one block per clip — the clip text, its rolled-up countries/regions,
and each extracted place with its label (and justification, when the run had them). Tag demos
write demo.md through it; `annotate_locations` re-renders locations.md from the deliverable
(purely a viewer — no LLM calls).
"""
from __future__ import annotations

import pandas as pd

from ...core.tables import load_paragraphs, paragraphs_by_interview
from ...errors import ToolkitError
from ...project import Project

ROLE_LABEL = {"Narrator": "N", "Interviewer": "Q"}


def clip_text_md(start: int, end: int, para_indexed: pd.DataFrame) -> str:
    """The clip's paragraphs as a markdown blockquote, one paragraph per line."""
    sub = para_indexed.loc[start:end]
    lines = [f"> **{ROLE_LABEL.get(r.speaker_role, 'O')}** {r.speech}" for r in sub.itertuples()]
    return "\n>\n".join(lines)


def places_md(rows: pd.DataFrame) -> str:
    """The extracted places for one clip: `place -> label (kind) — justification`."""
    if rows.empty:
        return "_(no place tagged)_"
    out = []
    for r in rows.itertuples():
        just = f" — {r.justification}" if r.justification else ""
        out.append(f"- `{r.place}` → **{r.label}** *({r.kind})*{just}")
    return "\n".join(out)


def write_review_md(project: Project, wide: pd.DataFrame, long: pd.DataFrame,
                    para_by_interview: dict[str, pd.DataFrame], filename: str, title: str):
    diag_dir = project.diags_dir / "locations"
    diag_dir.mkdir(parents=True, exist_ok=True)
    sel = wide.sort_values(["interview_id", "start_paragraph_idx"]).reset_index(drop=True)
    model = sel["model"].iloc[0] if len(sel) else "?"
    reasoning = sel["reasoning_effort"].iloc[0] if len(sel) else "?"
    n_place = int(sel["has_place"].sum()) if len(sel) else 0
    md = [f"# {title} — {len(sel)} clips",
          f"\n*{model} · reasoning={reasoning} · {n_place}/{len(sel)} clips tagged to ≥1 place · "
          f"marker legend: **N** narrator, **Q** interviewer, **O** other*\n"]
    for r in sel.itertuples():
        md.append(f"\n---\n\n## {r.clip_id}\n"
                  f"*{r.interview_id} · {r.start_ts}–{r.end_ts} · {r.n_paragraphs} paras, "
                  f"{r.total_words} words*\n")
        md.append(clip_text_md(int(r.start_paragraph_idx), int(r.end_paragraph_idx),
                               para_by_interview[r.interview_id]))
        md.append(f"\n**Countries:** {r.countries or '—'}  ·  **Regions:** {r.regions or '—'}\n")
        md.append(places_md(long[long["clip_id"] == r.clip_id]))
    path = diag_dir / filename
    path.write_text("\n".join(md) + "\n")
    return path


def annotate_locations(project: Project) -> None:
    out_dir = project.outputs_dir / "locations"
    wide_path = out_dir / "clip_locations.parquet"
    if not wide_path.exists():
        raise ToolkitError(f"{wide_path} not found. Run `toolkit locations tag` first.")
    wide = pd.read_parquet(wide_path)
    long = pd.read_parquet(out_dir / "clip_locations_long.parquet")
    para_by_interview = paragraphs_by_interview(load_paragraphs(project))
    path = write_review_md(project, wide, long, para_by_interview, "locations.md",
                           title="Clip locations")
    print(f"Wrote {path}")
