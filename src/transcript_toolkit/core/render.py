"""Text renderings of transcript material fed to models or review files.

BYTE-STABILITY WARNING: rendered text feeds cache keys and demo fingerprints. Any cosmetic
change here invalidates users' caches and recorded demos. The formats are ports of the
working repo's renderers — keep them byte-identical unless the change is deliberate.

Families:
- plain interview rendering (summarize): `Speaker: text` at each turn start, continuations on
  their own unlabeled lines — no timestamps/indices.
- plain clip rendering (topics/locations tagging): one `[Q]/[N]/[O] speech` line per paragraph —
  role marker only, since indices/timestamps are irrelevant to tagging.
- full paragraph rendering (clipping/labeling) lives with the clip step, which owns its format.
"""
from __future__ import annotations

import pandas as pd

ROLE_MARKER = {"Interviewer": "[Q]", "Narrator": "[N]"}


def render_session(para_df: pd.DataFrame) -> str:
    lines: list[str] = []
    for r in para_df.sort_values("paragraph_idx").itertuples():
        if r.paragraph_idx_in_turn == 0:
            lines.append(f"{r.speaker_label}: {r.speech}")
        else:
            lines.append(r.speech)
    return "\n".join(lines)


def render_interview(session_frames: list[pd.DataFrame]) -> str:
    """One interview unit (>=1 session, in id order). Pooled sessions get labeled dividers."""
    if len(session_frames) == 1:
        return render_session(session_frames[0])
    parts = [f"----- Session {i} -----\n\n{render_session(sf)}"
             for i, sf in enumerate(session_frames, start=1)]
    return "\n\n".join(parts)


def format_paragraph_plain(role: str, speech: str) -> str:
    """One tagging-input paragraph line: role marker + speech, nothing else."""
    return f"{ROLE_MARKER.get(role, '[O]')} {speech}"


def render_clip_plain(clip_id: str, start: int, end: int, para_indexed: pd.DataFrame) -> str:
    """One clip's paragraphs as per-call user content for the taggers. `para_indexed` is one
    interview's paragraphs indexed by paragraph_idx (see tables.paragraphs_by_interview)."""
    sub = para_indexed.loc[start:end]
    expected = end - start + 1
    if len(sub) != expected:
        raise RuntimeError(
            f"clip {clip_id}: expected {expected} paragraphs in [{start}, {end}], got {len(sub)} "
            f"(clips/paragraphs version skew? re-run `toolkit clip` after the last `toolkit import`)")
    return "\n".join(format_paragraph_plain(r.speaker_role, r.speech) for r in sub.itertuples()) + "\n"


def format_paragraph_full(idx: int, ts: str, role: str, word_count: int, speech: str) -> str:
    """One clipping/labeling paragraph line: `[idx] [HH:MM:SS] [role] (Xw) speech`.
    The timestamp is dropped (no placeholder) when empty; the `(Xw)` word-count flag lets the
    model apply the prompt's "substantial paragraph" threshold without counting words."""
    marker = ROLE_MARKER.get(role, "[O]")
    ts_str = f"[{ts}] " if ts else ""
    return f"[{idx}] {ts_str}{marker} ({word_count}w) {speech}"
