"""Annotated review HTML for clip location tags (diags/locations/).

`write_review_html` renders one section per clip — the clip text, its rolled-up countries/regions,
and each extracted place with its label (and justification, when the run had them). Tag demos write
demo.html through it; `annotate_locations` re-renders locations.html from the deliverable (purely a
viewer — no LLM calls). Self-contained pages, openable in any browser.
"""
from __future__ import annotations

import pandas as pd

from ...core.reviewdoc import document, esc, role_badge
from ...core.tables import load_paragraphs, paragraphs_by_interview
from ...errors import ToolkitError
from ...project import Project


def clip_text_html(start: int, end: int, para_indexed: pd.DataFrame) -> str:
    """The clip's paragraphs as a blockquote, one paragraph per line with its role badge."""
    sub = para_indexed.loc[start:end]
    lines = [f"<p>{role_badge(r.speaker_role)} {esc(r.speech)}</p>" for r in sub.itertuples()]
    return "<blockquote>\n" + "\n".join(lines) + "\n</blockquote>"


def places_html(rows: pd.DataFrame) -> str:
    """The extracted places for one clip: `place -> label (kind) — justification`."""
    if rows.empty:
        return '<p class="just">(no place tagged)</p>'
    items = []
    for r in rows.itertuples():
        just = f' <span class="just">— {esc(r.justification)}</span>' if r.justification else ""
        items.append(f'<li><code>{esc(r.place)}</code> → <span class="k">{esc(r.label)}</span> '
                     f'<span class="just">({esc(r.kind)})</span>{just}</li>')
    return '<div class="topics"><ul>\n' + "\n".join(items) + "\n</ul></div>"


def write_review_html(project: Project, wide: pd.DataFrame, long: pd.DataFrame,
                      para_by_interview: dict[str, pd.DataFrame], filename: str, title: str):
    diag_dir = project.diags_dir / "locations"
    diag_dir.mkdir(parents=True, exist_ok=True)
    sel = wide.sort_values(["interview_id", "start_paragraph_idx"]).reset_index(drop=True)
    model = sel["model"].iloc[0] if len(sel) else "?"
    reasoning = sel["reasoning_effort"].iloc[0] if len(sel) else "?"
    n_place = int(sel["has_place"].sum()) if len(sel) else 0
    subtitle = (f"<code>{esc(model)}</code> · reasoning=<code>{esc(reasoning)}</code> · "
                f"{n_place}/{len(sel)} clips tagged to ≥1 place · "
                f"badges: <b>N</b> narrator, <b>Q</b> interviewer, <b>O</b> other")
    body: list[str] = []
    for r in sel.itertuples():
        body.append('<section class="clip">')
        body.append(f'<h2>{esc(r.clip_id)} <span class="meta">{esc(r.interview_id)} · '
                    f'{esc(r.start_ts)}–{esc(r.end_ts)} · {r.n_paragraphs} paras, '
                    f'{r.total_words} words</span></h2>')
        body.append(clip_text_html(int(r.start_paragraph_idx), int(r.end_paragraph_idx),
                                   para_by_interview[r.interview_id]))
        body.append(f'<p><span class="k">Countries:</span> {esc(r.countries or "—")}  ·  '
                    f'<span class="k">Regions:</span> {esc(r.regions or "—")}</p>')
        body.append(places_html(long[long["clip_id"] == r.clip_id]))
        body.append("</section>")
    path = diag_dir / filename
    path.write_text(document(f"{title} — {len(sel)} clips", "\n".join(body), subtitle=subtitle))
    return path


def annotate_locations(project: Project) -> None:
    out_dir = project.outputs_dir / "locations"
    wide_path = out_dir / "clip_locations.parquet"
    if not wide_path.exists():
        raise ToolkitError(f"{wide_path} not found. Run `toolkit locations tag` first.")
    wide = pd.read_parquet(wide_path)
    long = pd.read_parquet(out_dir / "clip_locations_long.parquet")
    para_by_interview = paragraphs_by_interview(load_paragraphs(project))
    path = write_review_html(project, wide, long, para_by_interview, "locations.html",
                             title="Clip locations")
    print(f"Wrote {path}")
