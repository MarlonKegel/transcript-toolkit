"""`toolkit topics annotate` — per-interview annotated HTML from the topics deliverable.

One page per interview (diags/topics/{set}_{interview_id}.html), plus a {set}_index.html linking
them: each tagged clip with its topic scores inline — every topic scored >= 1, with the model's
one-line justification where one was recorded — followed by the clip's paragraphs. For
spot-checking whether the topics are well-chosen and the scoring is sound. Untagged clips and
procedural blocks are omitted; clip numbers still reflect position within the whole interview.
"""
from __future__ import annotations

import pandas as pd

from ...core.config import load_step_config
from ...core.reviewdoc import document, effective_ts, esc, para, write_index
from ...core.tables import load_clips, load_paragraphs
from ...errors import ToolkitError
from ...project import Project
from .taxonomy import load_topic_set

STEP = "topics"


def _topic_lines(clip_long: pd.DataFrame) -> str:
    """Topics scored >=1 for a clip, score desc, with the justification where recorded."""
    rows = clip_long[clip_long["score"] >= 1].sort_values(["score", "topic_id"],
                                                          ascending=[False, True])
    if rows.empty:
        return ('<p class="topics"><span class="k">Topics:</span> '
                '<span class="just">(none — clip fits no listed topic)</span></p>')
    items = []
    for r in rows.itertuples():
        just = f' <span class="just">— {esc(r.justification)}</span>' if str(r.justification).strip() else ""
        items.append(f'<li><span class="score">{int(r.score)}</span> {esc(r.topic_name)} '
                     f'<code>{esc(r.topic_id)}</code>{just}</li>')
    return ('<div class="topics"><span class="k">Topics:</span><ul>\n'
            + "\n".join(items) + "\n</ul></div>")


def _render_interview(interview_id: str, paragraphs: pd.DataFrame, clips: pd.DataFrame,
                      long_by_clip: dict[str, pd.DataFrame]) -> str:
    clips = clips.sort_values("start_paragraph_idx").reset_index(drop=True)
    clip_number = {c.clip_id: i for i, c in enumerate(clips.itertuples(), start=1)}
    paragraphs = paragraphs.sort_values("paragraph_idx")

    tagged = [c for c in clips.itertuples() if c.clip_id in long_by_clip]
    subtitle = f"<b>{len(tagged)}</b> tagged clips shown of {len(clips)} in interview"

    body: list[str] = []
    for c in tagged:
        start_idx, end_idx = int(c.start_paragraph_idx), int(c.end_paragraph_idx)
        block = list(paragraphs[(paragraphs["paragraph_idx"] >= start_idx)
                                & (paragraphs["paragraph_idx"] <= end_idx)].itertuples())
        words = sum(int(r.word_count) for r in block)
        span = (f"paragraph {start_idx}" if start_idx == end_idx
                else f"paragraphs {start_idx}–{end_idx}")
        dur = (f" · {c.duration_seconds / 60:.1f} min"
               if (c.duration_seconds is not None and not pd.isna(c.duration_seconds)) else "")
        body.append('<section class="clip">')
        body.append(f'<h2>Clip {clip_number[c.clip_id]} <span class="meta">{esc(span)} · '
                    f'{len(block)} paragraph(s) · {words} words{esc(dur)}</span></h2>')
        body.append(_topic_lines(long_by_clip[c.clip_id]))
        body.extend(para(int(r.paragraph_idx), effective_ts(r), r.speaker_role, r.speech) for r in block)
        body.append("</section>")
    return document(interview_id, "\n".join(body), subtitle=subtitle)


def annotate_topics(project: Project, set_name: str | None = None) -> None:
    cfg = load_step_config(project, STEP)
    tset = load_topic_set(project, cfg, set_name)
    sset = tset.name
    long_path = project.outputs_dir / "topics" / f"{sset}_clip_topics_long.parquet"
    if not long_path.exists():
        raise ToolkitError(f"{long_path} not found. Run `toolkit topics tag` first.")

    paragraphs_df = load_paragraphs(project)
    clips_df = load_clips(project)
    long_df = pd.read_parquet(long_path)
    long_by_clip = {cid: g for cid, g in long_df.groupby("clip_id")}

    out_dir = project.diags_dir / "topics"
    out_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for iid in sorted(long_df["interview_id"].unique()):
        sub_p = paragraphs_df[paragraphs_df["interview_id"] == iid]
        sub_c = clips_df[clips_df["interview_id"] == iid]
        sub_long = {cid: long_by_clip[cid] for cid in sub_c["clip_id"] if cid in long_by_clip}
        html = _render_interview(iid, sub_p, sub_c, sub_long)
        path = out_dir / f"{sset}_{iid}.html"
        path.write_text(html)
        entries.append((path.name, iid, f"{len(sub_long)} tagged clips"))
        print(f"  [{iid}] {len(sub_p)} paragraphs / {len(sub_c)} clips "
              f"({len(sub_long)} tagged) -> {path}")
    index = write_index(out_dir / f"{sset}_index.html", f"Topics ‘{sset}’ — review", entries)
    print(f"Index: {index}")
