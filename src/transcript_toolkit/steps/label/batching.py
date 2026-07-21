"""Clip batching for `toolkit label` (ported from the working repo's label-clips/scripts/utils.py).

Consecutive clips are grouped greedily up to a token budget; each batch carries its adjacent
clips as read-only neighbour context. Token estimates come from steps.clip.chunking so the
two steps' numbers line up.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LabelBatch:
    interview_id: str
    batch_idx: int
    clip_ids: list[str]          # clips to label, in clip order (a partition of the interview's clips)
    prev_clip_id: str | None     # read-only preceding-clip context (None for the first batch)
    next_clip_id: str | None     # read-only following-clip context (None for the last batch)
    est_tokens: int              # estimated input tokens over the to-label clips


def batch_clips(interview_id: str, ordered_clip_ids: list[str], clip_tokens: dict[str, int],
                batch_threshold: int) -> list[LabelBatch]:
    """Greedily group consecutive clips (already in clip order) into batches up to
    `batch_threshold` input tokens. Never splits a clip. A single clip whose own
    estimate exceeds the threshold becomes its own (over-budget) batch with a warning.

    Each batch carries the adjacent clips (in clip order) as read-only neighbour
    context; the to-label sets partition the interview's clips exactly once.
    """
    groups: list[list[int]] = []
    cur: list[int] = []
    cur_tok = 0
    for pos, cid in enumerate(ordered_clip_ids):
        t = clip_tokens[cid]
        if cur and cur_tok + t > batch_threshold:
            groups.append(cur)
            cur = []
            cur_tok = 0
        cur.append(pos)
        cur_tok += t
    if cur:
        groups.append(cur)

    batches: list[LabelBatch] = []
    for bi, positions in enumerate(groups):
        first, last = positions[0], positions[-1]
        clip_ids = [ordered_clip_ids[p] for p in positions]
        est = sum(clip_tokens[c] for c in clip_ids)
        if len(clip_ids) == 1 and est > batch_threshold:
            print(f"WARNING: {interview_id} clip {clip_ids[0]} estimated {est} tokens "
                  f"exceeds batch_threshold {batch_threshold}; running it as its own batch")
        prev_id = ordered_clip_ids[first - 1] if first > 0 else None
        next_id = ordered_clip_ids[last + 1] if last + 1 < len(ordered_clip_ids) else None
        batches.append(LabelBatch(interview_id, bi, clip_ids, prev_id, next_id, est))
    return batches
