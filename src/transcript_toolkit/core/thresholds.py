"""Clip->interview rollup thresholds (ported byte-identical from tag-topics utils).

Two schemes, chosen per topic set / for locations in config:
- flat: one bar for every topic (`threshold_pct`);
- binned (rarity/frequency-width): topics split into len(thresholds) EQUAL-WIDTH clip-frequency
  bands; the rarest band clears the lowest bar, the commonest the highest — lifts rare topics
  off zero without flooding common ones. Same-frequency topics always share a bar.
"""
from __future__ import annotations

import pandas as pd


def freq_width_thresholds(freq: pd.Series, thresholds) -> pd.Series:
    """topic -> threshold Series; `thresholds` is the ascending bar list (rarest band first)."""
    thr = sorted(thresholds)
    bins = pd.cut(freq, bins=len(thr), labels=False, include_lowest=True)  # 0..k-1, 0 = rarest
    return bins.map(lambda b: float(thr[int(b)]))


def flat_thresholds(freq: pd.Series, threshold_pct: float) -> pd.Series:
    return pd.Series(float(threshold_pct), index=freq.index)
