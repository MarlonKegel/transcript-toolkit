"""Chunking for `toolkit clip` (ported from the working repo's clipping/scripts/utils.py).

BYTE-STABILITY WARNING: `estimate_paragraph_tokens` drives `chunk_paragraphs`, whose output
shapes every clip call's user content and therefore cache keys and demo fingerprints. Keep
the logic byte-identical to the working repo unless the change is deliberate.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

# Token estimation constants (calibrated against the working repo's cache records; ~6.6% mean overshoot).
PARAGRAPH_PREFIX_TOKENS = 12     # "[idx] [HH:MM:SS] [N] (Xw) " + newline
TOKENS_PER_WORD = 1.3
CHUNK_OVERHEAD_BASE = 700        # prompt instructions
CHUNK_OVERHEAD_LOCKED = 500      # extra for chunks >= 1 (locked-context preamble)


def estimate_paragraph_tokens(word_count: int) -> int:
    """Rough token count for a formatted paragraph line in user_content."""
    return int(round(word_count * TOKENS_PER_WORD + PARAGRAPH_PREFIX_TOKENS))


@dataclass
class Chunk:
    chunk_idx: int
    shown_start: int            # first paragraph_idx visible to the model
    shown_end: int              # last paragraph_idx visible to the model
    decision_start: int         # first paragraph_idx in the decision region (== shown_start for chunk 0)
    owned_start: int            # first paragraph_idx in final-say region (kept after stitching)
    owned_end: int              # last paragraph_idx in final-say region
    est_tokens: int

    @property
    def is_first(self) -> bool:
        return self.chunk_idx == 0


def chunk_paragraphs(df_interview: pd.DataFrame, chunk_threshold: int, overlap_paragraphs: int) -> list[Chunk]:
    """Balanced split. n_chunks = (total_tokens // chunk_threshold) + 1.

    For interviews under the threshold, returns a single chunk covering everything.
    For longer interviews, splits paragraphs into balanced owned regions and adds
    overlap (half locked, half redecide) at each seam.
    """
    df_sorted = df_interview.sort_values("paragraph_idx").reset_index(drop=True)
    n = len(df_sorted)
    para_idxs = df_sorted["paragraph_idx"].tolist()
    para_tokens = [estimate_paragraph_tokens(int(w)) for w in df_sorted["word_count"]]

    total_tokens = sum(para_tokens) + CHUNK_OVERHEAD_BASE
    n_chunks = (total_tokens // chunk_threshold) + 1

    K = overlap_paragraphs
    K_half = K // 2

    paragraph_token_total = sum(para_tokens)
    target_owned_tokens = paragraph_token_total / n_chunks

    owned_ranges: list[tuple[int, int]] = []
    acc = 0
    cur_start = 0
    for i in range(n):
        acc += para_tokens[i]
        last_chunk_to_close = len(owned_ranges) == n_chunks - 1
        if not last_chunk_to_close and acc >= target_owned_tokens:
            owned_ranges.append((cur_start, i))
            cur_start = i + 1
            acc = 0
    owned_ranges.append((cur_start, n - 1))
    assert len(owned_ranges) == n_chunks
    assert all(s <= e for s, e in owned_ranges), f"Empty chunk: {owned_ranges}"

    chunks: list[Chunk] = []
    for ci, (own_start_i, own_end_i) in enumerate(owned_ranges):
        is_last = ci == n_chunks - 1
        is_first = ci == 0
        shown_start_i = own_start_i if is_first else max(0, own_start_i - K_half)
        decision_start_i = own_start_i
        shown_end_i = own_end_i if is_last else min(n - 1, own_end_i + K_half)
        overhead = CHUNK_OVERHEAD_BASE + (0 if is_first else CHUNK_OVERHEAD_LOCKED)
        tokens = overhead + sum(para_tokens[shown_start_i:shown_end_i + 1])
        chunks.append(Chunk(
            chunk_idx=ci,
            shown_start=int(para_idxs[shown_start_i]),
            shown_end=int(para_idxs[shown_end_i]),
            decision_start=int(para_idxs[decision_start_i]),
            owned_start=int(para_idxs[own_start_i]),
            owned_end=int(para_idxs[own_end_i]),
            est_tokens=tokens,
        ))
    return chunks


def ts_to_seconds(ts: str) -> int | None:
    """Convert an "HH:MM:SS" transcript timestamp to seconds; "" -> None."""
    if not ts:
        return None
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)
