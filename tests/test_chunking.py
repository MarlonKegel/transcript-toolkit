import pandas as pd
import pytest

from transcript_toolkit.steps.clip.chunking import (
    CHUNK_OVERHEAD_BASE,
    CHUNK_OVERHEAD_LOCKED,
    chunk_paragraphs,
    estimate_paragraph_tokens,
    ts_to_seconds,
)


def make_df(n: int, words: int = 100) -> pd.DataFrame:
    return pd.DataFrame({"paragraph_idx": range(n), "word_count": [words] * n})


def test_estimate_paragraph_tokens():
    assert estimate_paragraph_tokens(100) == 142          # 100 * 1.3 + 12
    assert estimate_paragraph_tokens(0) == 12             # prefix only


def test_ts_to_seconds():
    assert ts_to_seconds("01:02:03") == 3723
    assert ts_to_seconds("00:00:00") == 0
    assert ts_to_seconds("") is None


def test_single_chunk_covers_everything():
    df = make_df(10)                                      # ~2,120 tokens, far under threshold
    chunks = chunk_paragraphs(df, 20000, 20)
    assert len(chunks) == 1
    c = chunks[0]
    assert c.is_first
    assert (c.shown_start, c.shown_end) == (0, 9)
    assert (c.decision_start, c.owned_start, c.owned_end) == (0, 0, 9)
    assert c.est_tokens == CHUNK_OVERHEAD_BASE + 10 * estimate_paragraph_tokens(100)


def test_multi_chunk_regions():
    n, words, threshold, overlap = 100, 100, 5000, 20
    df = make_df(n, words)
    per = estimate_paragraph_tokens(words)
    expected_n = (n * per + CHUNK_OVERHEAD_BASE) // threshold + 1
    chunks = chunk_paragraphs(df, threshold, overlap)
    assert len(chunks) == expected_n == 3

    # Owned regions partition [0, n-1] contiguously.
    assert chunks[0].owned_start == 0 and chunks[-1].owned_end == n - 1
    for a, b in zip(chunks, chunks[1:]):
        assert b.owned_start == a.owned_end + 1

    k_half = overlap // 2
    for i, c in enumerate(chunks):
        # Decision region always starts at the owned region.
        assert c.decision_start == c.owned_start
        # First chunk has no locked context; later chunks look back K/2 paragraphs.
        if i == 0:
            assert c.shown_start == c.owned_start
        else:
            assert c.shown_start == max(0, c.owned_start - k_half)
        # Last chunk has no redecide overlap; earlier chunks look ahead K/2 paragraphs.
        if i == len(chunks) - 1:
            assert c.shown_end == c.owned_end
        else:
            assert c.shown_end == min(n - 1, c.owned_end + k_half)
        # Locked-context overhead applies to chunks >= 1 only.
        overhead = CHUNK_OVERHEAD_BASE + (0 if i == 0 else CHUNK_OVERHEAD_LOCKED)
        n_shown = c.shown_end - c.shown_start + 1
        assert c.est_tokens == overhead + n_shown * per


def test_chunks_balanced_by_tokens():
    # Uneven paragraphs: chunker balances estimated tokens, not paragraph counts.
    n = 60
    df = pd.DataFrame({"paragraph_idx": range(n),
                       "word_count": [300 if i < 20 else 20 for i in range(n)]})
    chunks = chunk_paragraphs(df, 3000, 10)
    assert len(chunks) >= 2
    tokens = [estimate_paragraph_tokens(int(w)) for w in df["word_count"]]
    target = sum(tokens) / len(chunks)
    owned_tokens = [sum(tokens[c.owned_start:c.owned_end + 1]) for c in chunks]
    # Every non-final owned region stops within one paragraph of crossing the target.
    for t in owned_tokens[:-1]:
        assert t >= target
        assert t - max(tokens) < target


def test_nonzero_based_paragraph_idx_passthrough():
    # Chunk boundaries are reported in paragraph_idx space, not positional space.
    df = pd.DataFrame({"paragraph_idx": range(100, 110), "word_count": [50] * 10})
    (c,) = chunk_paragraphs(df, 20000, 20)
    assert (c.shown_start, c.shown_end) == (100, 109)
