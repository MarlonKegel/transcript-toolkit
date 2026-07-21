"""Text renderings of transcript material fed to models or review files.

BYTE-STABILITY WARNING: rendered text feeds cache keys and demo fingerprints. Any cosmetic
change here invalidates users' caches and recorded demos. The formats are ports of the
working repo's renderers — keep them byte-identical unless the change is deliberate.

Two families (more added as steps are ported):
- plain interview rendering (summarize): `Speaker: text` at each turn start, continuations on
  their own unlabeled lines — no timestamps/indices.
"""
from __future__ import annotations

import pandas as pd


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
