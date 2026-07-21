"""`toolkit topics annotate` — per-interview annotated Markdown from the topics deliverable.

One md per interview (diags/topics/{set}_{interview_id}.md): each tagged clip with its topic
scores inline — every topic scored >= 1, with the model's one-line justification where one was
recorded — followed by the clip's paragraphs. For spot-checking whether the topics are
well-chosen and the scoring is sound. Untagged clips and procedural blocks are omitted; clip
numbers still reflect position within the whole interview.
"""
from __future__ import annotations

import pandas as pd

from ...core.config import load_step_config
from ...core.tables import load_clips, load_paragraphs
from ...errors import ToolkitError
from ...project import Project
from .taxonomy import load_topic_set

STEP = "topics"

ROLE_MARKER = {"Interviewer": "[Q]", "Narrator": "[N]", "Other": "[O]"}


def _effective_ts(r) -> str:
    return r.sub_time_start or r.turn_time_start


def _render_paragraph(r) -> str:
    marker = ROLE_MARKER.get(r.speaker_role, "[?]")
    return f"**[{int(r.paragraph_idx)}]** `[{_effective_ts(r)}]` {marker} {r.speech}"


def _topic_lines(clip_long: pd.DataFrame) -> list[str]:
    """Topics scored >=1 for a clip, score desc, with the justification where recorded."""
    rows = clip_long[clip_long["score"] >= 1].sort_values(["score", "topic_id"],
                                                          ascending=[False, True])
    if rows.empty:
        return ["**Topics:** _(none — clip fits no listed topic)_"]
    out = ["**Topics:**"]
    for r in rows.itertuples():
        just = f" — {r.justification}" if str(r.justification).strip() else ""
        out.append(f"- **{int(r.score)}** · {r.topic_name} (`{r.topic_id}`){just}")
    return out


def _render_interview(interview_id: str, paragraphs: pd.DataFrame, clips: pd.DataFrame,
                      long_by_clip: dict[str, pd.DataFrame]) -> str:
    clips = clips.sort_values("start_paragraph_idx").reset_index(drop=True)
    clip_number = {c.clip_id: i for i, c in enumerate(clips.itertuples(), start=1)}
    paragraphs = paragraphs.sort_values("paragraph_idx")

    tagged = [c for c in clips.itertuples() if c.clip_id in long_by_clip]
    out = ["\n".join([
        f"# {interview_id}", "",
        f"**Tagged clips shown**: {len(tagged)} of {len(clips)} in interview",
    ]), ""]

    for c in tagged:
        start_idx, end_idx = int(c.start_paragraph_idx), int(c.end_paragraph_idx)
        block = list(paragraphs[(paragraphs["paragraph_idx"] >= start_idx)
                                & (paragraphs["paragraph_idx"] <= end_idx)].itertuples())
        words = sum(int(r.word_count) for r in block)
        span = (f"paragraphs {start_idx}" if start_idx == end_idx
                else f"paragraphs {start_idx}–{end_idx}")
        dur = (f" · {c.duration_seconds / 60:.1f} min"
               if (c.duration_seconds is not None and not pd.isna(c.duration_seconds)) else "")
        out += [f"## Clip {clip_number[c.clip_id]} — {span} · {len(block)} paragraph(s) · "
                f"{words} words{dur}", ""]
        out += _topic_lines(long_by_clip[c.clip_id])
        out.append("")
        for r in block:
            out += [_render_paragraph(r), ""]
        out += ["---", ""]
    return "\n".join(out).rstrip() + "\n"


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
    for iid in sorted(long_df["interview_id"].unique()):
        sub_p = paragraphs_df[paragraphs_df["interview_id"] == iid]
        sub_c = clips_df[clips_df["interview_id"] == iid]
        sub_long = {cid: long_by_clip[cid] for cid in sub_c["clip_id"] if cid in long_by_clip}
        md = _render_interview(iid, sub_p, sub_c, sub_long)
        path = out_dir / f"{sset}_{iid}.md"
        path.write_text(md)
        print(f"  [{iid}] {len(sub_p)} paragraphs / {len(sub_c)} clips "
              f"({len(sub_long)} tagged) -> {path}")
