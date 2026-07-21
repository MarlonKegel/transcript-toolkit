"""`toolkit topics rollup` — aggregate clip topic scores to interview (narrator) tags.

An interview is tagged to a topic when the share of its clips ASSIGNED (top score, "does
belong") to that topic clears a threshold. The threshold scheme comes from config
(topics.sets.<set>.rollup): **flat** applies one bar to every topic; **binned** splits the
topics into equal-width clip-frequency bands and gives the rarest band the lowest bar — an
equalizing tendency that lifts rare topics off zero without flooding the common ones. Clips
are pooled per narrator: session files combine via narrator_key; session-less ids are their
own narrator. Deterministic — no LLM calls, re-run freely after `toolkit topics tag`.
"""
from __future__ import annotations

import pandas as pd

from ...core.config import load_step_config, require
from ...core.ids import narrator_key
from ...core.tables import write_deliverable
from ...core.thresholds import flat_thresholds, freq_width_thresholds
from ...errors import ToolkitError
from ...project import Project
from .taxonomy import TopicSet, load_topic_set, resolve_set

STEP = "topics"


def pooled_shares(project: Project, cfg: dict, tset: TopicSet):
    """Pool the clip-level wide deliverable per narrator. Returns (counts, pct, freq,
    n_clips, n_sessions): clips-assigned counts and shares (%) per narrator x topic,
    corpus-wide clip frequency per topic, and per-narrator clip/session counts."""
    wide_path = project.outputs_dir / "topics" / f"{tset.name}_clip_topics_wide.parquet"
    if not wide_path.exists():
        raise ToolkitError(f"{wide_path} not found. Run `toolkit topics tag` first.")
    w = pd.read_parquet(wide_path)
    tids = tset.ids
    maxv = max(int(v) for v in cfg["score_values"])   # "assigned" = the top score
    session_regex = load_step_config(project, "import")["session_regex"]

    # Narrator pooling: session files pool per narrator (narrator_key strips the trailing
    # session token); ids without one pass through unchanged and are their own narrator.
    w["interview_key"] = w["interview_id"].map(lambda i: narrator_key(i, session_regex))
    assigned = (w[tids] == maxv).astype(int)
    assigned["interview_key"] = w["interview_key"].values
    counts = assigned.groupby("interview_key")[tids].sum()
    n_clips = w.groupby("interview_key").size().reindex(counts.index)
    n_sessions = w.groupby("interview_key")["interview_id"].nunique().reindex(counts.index)
    pct = counts.div(n_clips, axis=0) * 100
    freq = counts.sum()
    return counts, pct, freq, n_clips, n_sessions


def scheme_thresholds(rollup_cfg: dict | None, freq: pd.Series, sset: str) -> tuple[pd.Series, str]:
    """Per-topic threshold Series + a human-readable scheme description, from the set's
    rollup config: {scheme: flat, threshold_pct: N} or {scheme: binned, thresholds: [...]}."""
    if not rollup_cfg or rollup_cfg.get("scheme") is None:
        raise ToolkitError(
            f"config.yaml topics.sets.{sset}.rollup needs a scheme: "
            f"{{scheme: flat, threshold_pct: N}} or {{scheme: binned, thresholds: [...]}}.")
    scheme = rollup_cfg["scheme"]
    if scheme == "flat":
        pct0 = rollup_cfg.get("threshold_pct")
        if pct0 is None:
            raise ToolkitError(f"topics.sets.{sset}.rollup: scheme 'flat' needs threshold_pct.")
        return flat_thresholds(freq, float(pct0)), f"flat {float(pct0):g}%"
    if scheme == "binned":
        bars = rollup_cfg.get("thresholds")
        if not bars:
            raise ToolkitError(f"topics.sets.{sset}.rollup: scheme 'binned' needs a thresholds list.")
        return (freq_width_thresholds(freq, bars),
                f"freq-width-binned {min(bars):g}-{max(bars):g}% ({len(bars)} bins)")
    raise ToolkitError(f"Unknown rollup scheme {scheme!r} for set '{sset}'; "
                       f"expected 'flat' or 'binned'.")


def run_topics_rollup(project: Project, set_name: str | None = None) -> pd.DataFrame:
    cfg = load_step_config(project, STEP)
    require(cfg, ["score_values"], STEP)
    tset = load_topic_set(project, cfg, set_name)
    sset = tset.name
    tids = tset.ids
    name_by_id = {t["id"]: t["name"] for t in tset.topics}
    _, entry = resolve_set(cfg, sset)

    counts, pct, freq, n_clips, n_sessions = pooled_shares(project, cfg, tset)
    thr_by_topic, scheme_desc = scheme_thresholds(entry.get("rollup"), freq, sset)
    tagged = pct.ge(thr_by_topic, axis=1)

    # --- long: narrator x topic (full record; filter tagged==True for the tags) ------------
    long = (pct.round(2).reset_index()
            .melt("interview_key", var_name="topic_id", value_name="pct_clips"))
    long["topic_name"] = long["topic_id"].map(name_by_id)
    long["n_clips_assigned"] = [int(counts.loc[k, t])
                                for k, t in zip(long["interview_key"], long["topic_id"])]
    long["n_clips_total"] = long["interview_key"].map(n_clips).astype(int)
    long["threshold_pct"] = long["topic_id"].map(thr_by_topic)   # the bar applied to this topic
    long["tagged"] = [bool(tagged.loc[k, t])
                      for k, t in zip(long["interview_key"], long["topic_id"])]
    long = long[["interview_key", "topic_id", "topic_name", "n_clips_assigned", "n_clips_total",
                 "pct_clips", "threshold_pct", "tagged"]]

    # --- wide: one row per narrator ---------------------------------------------------------
    wide = pd.DataFrame(index=counts.index)
    wide["n_sessions"] = n_sessions.astype(int)
    wide["n_clips"] = n_clips.astype(int)
    for t in tids:                                               # per-topic assigned share (%)
        wide[t] = pct[t].round(1)
    wide["topics"] = ["|".join(t for t in tids if tagged.loc[k, t]) for k in wide.index]
    wide["n_topics"] = tagged.sum(axis=1).astype(int)
    wide = wide.reset_index()

    out_dir = project.outputs_dir / "topics"
    write_deliverable(long, out_dir / f"{sset}_interview_topics_long.parquet",
                      sort_by=["interview_key", "topic_id"])
    write_deliverable(wide, out_dir / f"{sset}_interview_topics_wide.parquet",
                      sort_by="interview_key")

    # --- summary -----------------------------------------------------------------------------
    n_int = len(wide)
    print(f"Topic rollup · set '{sset}' · thresholds: {scheme_desc}")
    print(f"{n_int} interviews ({int(n_sessions.sum())} sessions / {int(n_clips.sum())} clips), "
          f"clips/interview {int(n_clips.min())}–{int(n_clips.max())} "
          f"(median {int(n_clips.median())})")
    if thr_by_topic.nunique() > 1:
        print("rarity bins (clip-freq of each topic -> its bar):")
        for th in sorted(thr_by_topic.unique()):
            grp = sorted((t for t in tids if thr_by_topic[t] == th), key=lambda x: -int(freq[x]))
            print(f"  {th:>4g}% : " + ", ".join(f"{t}({int(freq[t])})" for t in grp))
    ntop = wide["n_topics"]
    print(f"topics/interview: mean {ntop.mean():.2f}, range {int(ntop.min())}–{int(ntop.max())}; "
          f"interviews with no topic: {int((ntop == 0).sum())}")
    reach = tagged.sum(axis=0).sort_values(ascending=False)
    print(f"interviews reached per topic (of {n_int})  [bar = its share-of-clips threshold]:")
    for t, v in reach.items():
        print(f"  {t:<24} {int(v):>3}   bar {thr_by_topic[t]:g}%")
    print(f"\nWrote {out_dir}/{sset}_interview_topics_{{long,wide}}.{{parquet,csv}}")
    return wide
