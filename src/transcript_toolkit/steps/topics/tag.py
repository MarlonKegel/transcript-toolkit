"""`toolkit topics tag` — score every clip against one topic set (deductive tagging).

One structured-output LLM call per clip: the stable instructions prefix (task/rubric prompt
[+ justification addendum] + topic-id legend + generated taxonomy) is shared across calls and
served from the provider's prompt cache; the only variable part is the clip text. Demo-first:
`--demo` tags a seeded clip sample with justifications ON and writes the review md only; a
full run is demo-gated, confirms cost, and writes outputs/topics/{set}_clip_topics_{wide,long}.
Idempotent + resumable via the per-call cache (.toolkit/cache/topics_{set}.jsonl).
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from threading import Lock
from typing import Literal

import pandas as pd
from pydantic import create_model

from ...core import cost as costmod
from ...core.cache import JsonlAppender, cache_key, latest_records
from ...core.config import load_step_config, require
from ...core.console import confirm_or_abort
from ...core.llm import build_schema, call_llm, check_levels, openai_client
from ...core.render import render_clip_plain
from ...core.sampling import sample_clips_spread
from ...core.tables import (load_clips, load_paragraphs, merge_subset,
                            paragraphs_by_interview, write_deliverable)
from ...errors import ToolkitError
from ...project import Project
from ...state import check_demo_gate, record_demo, record_full
from ..summarize import load_prompt
from .taxonomy import TopicSet, build_legend, load_topic_set

STEP = "topics"


# --- assembly -------------------------------------------------------------------------------

def build_instructions(prompt_text: str, topics: list[dict], taxonomy_text: str,
                       justify_addendum: str = "") -> str:
    """Assemble the full (stable, cacheable) instructions block sent to the model:
    task/rubric prompt (+ the optional justification addendum) + topic-id legend + topic
    definitions. Ported byte-identical from the working repo's tag-topics utils (its
    validate_taxonomy is obsolete here: the taxonomy text is generated, not hand-edited)."""
    prompt = f"{prompt_text}\n\n{justify_addendum}" if justify_addendum else prompt_text
    return f"{prompt}\n\n{build_legend(topics)}\n\n## Topic definitions\n\n{taxonomy_text}\n"


def build_scores_model(topic_ids: list[str], score_values: tuple[int, ...] = (0, 1, 2, 3),
                       justify: bool = True):
    """Build the Pydantic model for the structured response:

        {
          "scores":   { <topic_id>: <one of score_values>, ... for all topics },  # fixed keys, all required
          "evidence": [ { "topic_id": <one of the ids>, "justification": str }, ... ]   # only when justify
        }

    A fixed-key `scores` object guarantees exactly the configured topics are scored
    (and naturally allows all-zeros). `evidence` is a variable-length list carrying a
    one-line justification for the topics the model scored toward "belongs"; it is
    omitted entirely when `justify` is False (full runs that don't need rationales)."""
    score_fields = {tid: (Literal[tuple(score_values)], ...) for tid in topic_ids}
    scores = create_model("Scores", **score_fields)
    if not justify:
        return create_model("TopicScores", scores=(scores, ...))

    topic_id_type = Literal[tuple(topic_ids)]  # enum over the configured ids
    evidence = create_model("Evidence", topic_id=(topic_id_type, ...), justification=(str, ...))

    return create_model(
        "TopicScores",
        scores=(scores, ...),
        evidence=(list[evidence], ...),
    )


def validate_parsed(parsed: dict, topic_ids: list[str], model_cls, justify_min: int,
                    justify: bool) -> list[str]:
    """Schema already guarantees structure/enum; re-validate via Pydantic and (when
    justifications are on) add a soft consistency check: evidence present iff
    score >= justify_min (must match the justify addendum's "score 1 or 2" rule)."""
    errs: list[str] = []
    try:
        model_cls.model_validate(parsed)
    except Exception as e:  # noqa: BLE001 -- surface any schema drift loudly
        return [f"pydantic validation failed: {e}"]
    if not justify:
        return errs
    scores = parsed["scores"]
    expect = {tid for tid in topic_ids if scores[tid] >= justify_min}
    ev_ids = {e["topic_id"] for e in parsed.get("evidence", [])}
    missing = expect - ev_ids
    extra = ev_ids - expect
    if missing:
        errs.append(f"no justification for topics scored >={justify_min}: {sorted(missing)}")
    if extra:
        errs.append(f"justification for topics scored <{justify_min}: {sorted(extra)}")
    return errs


def _context(project: Project, set_name: str | None, justify: bool | None, demo: bool):
    cfg = load_step_config(project, STEP)
    require(cfg, ["model", "reasoning", "verbosity", "prompt", "justify_prompt", "max_workers",
                  "score_values", "justify_min_score", "demo_n_clips", "demo_seed"], STEP)
    check_levels(cfg["reasoning"], cfg["verbosity"])
    tset = load_topic_set(project, cfg, set_name)
    # A set may bring its own rubric (config sets.<set>.prompt) when its tagging rules differ
    # from the default — e.g. OSF's fine-grained Filter set with its specific+substantive bar.
    prompt_text = load_prompt(project, tset.prompt or cfg["prompt"])

    # Justifications default ON for demos (they are what you review) and OFF for full runs
    # (cheaper; the scores are the deliverable).
    use_justify = demo if justify is None else justify
    addendum = load_prompt(project, cfg["justify_prompt"]) if use_justify else ""
    instructions = build_instructions(prompt_text, tset.topics, tset.taxonomy_text, addendum)

    # The demo-gate fingerprint is computed over the justify-OFF (base) instructions in BOTH
    # demo and full runs. Demos default justify-on and full runs justify-off, so a fingerprint
    # over the actual instructions would make every demo permanently stale for the full run it
    # is meant to approve; keying on the base instructions lets a justify-on demo approve a
    # justify-off full run of the same base prompt + taxonomy (the addendum only adds
    # rationales — it does not change the scoring task).
    base_instructions = build_instructions(prompt_text, tset.topics, tset.taxonomy_text, "")
    fingerprint = cache_key(cfg["model"], cfg["reasoning"], cfg["verbosity"], base_instructions)
    return cfg, tset, use_justify, instructions, fingerprint


# --- run ------------------------------------------------------------------------------------

def run_topics_tag(project: Project, set_name: str | None = None, demo: bool = False,
                   sample_n: int | None = None, seed: int | None = None,
                   interviews: list[str] | None = None, justify: bool | None = None,
                   yes: bool = False, skip_demo_check: bool = False) -> pd.DataFrame:
    if demo and interviews:
        raise ToolkitError("--demo and --interview are mutually exclusive.")
    cfg, tset, use_justify, instructions, fingerprint = _context(project, set_name, justify, demo)
    sset = tset.name
    model, reasoning, verbosity = cfg["model"], cfg["reasoning"], cfg["verbosity"]

    clips_df = load_clips(project)
    para_by_interview = paragraphs_by_interview(load_paragraphs(project))

    if demo:
        n = int(sample_n if sample_n is not None else cfg["demo_n_clips"])
        s = int(seed if seed is not None else cfg["demo_seed"])
        wanted = sample_clips_spread(clips_df, n, s)
        selected = clips_df[clips_df["clip_id"].isin(wanted)]
    elif interviews:
        unknown = [i for i in interviews if i not in set(clips_df["interview_id"])]
        if unknown:
            raise ToolkitError(f"Unknown interview id(s): {', '.join(unknown)}. "
                               f"Available: {', '.join(sorted(clips_df['interview_id'].unique()))}")
        selected = clips_df[clips_df["interview_id"].isin(interviews)]
    else:
        selected = clips_df
    selected = selected.sort_values(["interview_id", "start_paragraph_idx"]).reset_index(drop=True)

    # Render every clip up front — version skew between clips and paragraphs fails loud here.
    texts = {row.clip_id: render_clip_plain(row.clip_id, int(row.start_paragraph_idx),
                                            int(row.end_paragraph_idx),
                                            para_by_interview[row.interview_id])
             for row in selected.itertuples()}

    cache_path = project.cache_dir / f"topics_{sset}.jsonl"
    cache = latest_records(cache_path, "cache_key")
    n_cached = sum(1 for cid in texts
                   if cache_key(model, reasoning, verbosity, instructions, texts[cid]) in cache)
    n_fresh = len(texts) - n_cached

    if not demo:
        check_demo_gate(project, f"topics:{sset}", fingerprint,
                        demo_command=f"toolkit topics tag --demo --set {sset}", skip=skip_demo_check)
        estimate = _estimate(cache, fingerprint, model, n_fresh)
        confirm_or_abort(
            f"Tag {len(selected)} clip(s) against topic set '{sset}' with {model} "
            f"({n_cached} already cached, {n_fresh} fresh API calls{estimate})?", yes)

    print(f"Tagging {len(selected)} clip(s) · set '{sset}' ({len(tset.ids)} topics) · "
          f"{model}/{reasoning} · justify={'on' if use_justify else 'off'} · "
          f"{n_cached} cached / {n_fresh} fresh")

    results = _run_clips(project, cfg, tset, sset, use_justify, instructions, fingerprint,
                         selected, texts, cache, cache_path)
    wide_df, long_df = _build_frames(selected, results, tset, cfg, model, reasoning)

    if demo:
        diag = _write_demo_md(project, sset, selected, texts, results, tset, model, reasoning)
        record_demo(project, f"topics:{sset}", fingerprint,
                    units=sorted(texts), diag=str(diag))
        print(f"\nDemo review file: {diag}")
        print("Review it; adjust config.yaml / prompts/ / the topic spreadsheet and re-demo if "
              f"needed. Then run `toolkit topics tag --set {sset}` for the full corpus.")
        return wide_df

    out_dir = project.outputs_dir / "topics"
    wide_path = out_dir / f"{sset}_clip_topics_wide.parquet"
    long_path = out_dir / f"{sset}_clip_topics_long.parquet"
    if interviews and wide_path.exists():
        wide_df = merge_subset(pd.read_parquet(wide_path), wide_df, "clip_id")
        long_df = merge_subset(pd.read_parquet(long_path), long_df, "clip_id")
    write_deliverable(wide_df, wide_path, sort_by=["interview_id", "clip_id"])
    write_deliverable(long_df, long_path, sort_by=["interview_id", "clip_id", "topic_id"])
    if not interviews:
        record_full(project, f"topics:{sset}", fingerprint, model=model, n_units=len(selected))
    _print_distribution(wide_df[wide_df["clip_id"].isin(texts)], tset, cfg)
    print(f"\nWrote {len(wide_df)} clip taggings -> {wide_path}\n"
          f"      {len(long_df)} clip x topic rows -> {long_path}")
    return wide_df


def _estimate(cache: dict, fingerprint: str, model: str, n_fresh: int) -> str:
    matching = [r for r in cache.values() if r.get("fingerprint") == fingerprint]
    per = costmod.mean_unit_cost(matching, model)
    if per is None or n_fresh == 0:
        return ""
    return f", ~${per[0] * n_fresh:.2f} est."


def _run_clips(project: Project, cfg: dict, tset: TopicSet, sset: str, use_justify: bool,
               instructions: str, fingerprint: str, selected: pd.DataFrame,
               texts: dict[str, str], cache: dict, cache_path) -> dict[str, dict]:
    model, reasoning, verbosity = cfg["model"], cfg["reasoning"], cfg["verbosity"]
    score_values = tuple(int(v) for v in cfg["score_values"])
    justify_min = int(cfg["justify_min_score"])
    model_cls = build_scores_model(tset.ids, score_values=score_values, justify=use_justify)
    schema = build_schema(model_cls, "topic_scores")
    prompt_cache_key_str = cache_key(model, reasoning, verbosity, instructions)
    client = None
    if any(cache_key(model, reasoning, verbosity, instructions, texts[cid]) not in cache
           for cid in texts):
        client = openai_client(project.root)
    appender = JsonlAppender(cache_path)
    lock = Lock()
    results: dict[str, dict] = {}
    warnings: list[tuple[str, list[str]]] = []

    def work(row) -> tuple[str, dict, bool, list[str]]:
        cid, iid = row.clip_id, row.interview_id
        user_content = texts[cid]
        ck = cache_key(model, reasoning, verbosity, instructions, user_content)
        with lock:
            hit = cache.get(ck)
        if hit is not None:
            parsed = {"scores": hit["scores"], "evidence": hit.get("evidence", [])}
            from_cache = True
        else:
            parsed, usage = call_llm(client, model, reasoning, verbosity, schema,
                                     instructions, user_content, prompt_cache_key_str,
                                     poll_interval_s=float(cfg.get("poll_interval_s", 4)),
                                     max_total_wait_s=float(cfg.get("max_total_wait_s", 1800)))
            record = {
                "cache_key": ck, "fingerprint": fingerprint, "set": sset,
                "clip_id": cid, "interview_id": iid,
                "scores": parsed["scores"], "evidence": parsed.get("evidence", []),
                "model": model, "reasoning_effort": reasoning, "verbosity": verbosity,
                "usage": usage, "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            appender.append(record)
            with lock:
                cache[ck] = record
            from_cache = False
        errs = validate_parsed(parsed, tset.ids, model_cls, justify_min, use_justify)
        return cid, parsed, from_cache, errs

    with ThreadPoolExecutor(max_workers=int(cfg["max_workers"])) as ex:
        futures = [ex.submit(work, row) for row in selected.itertuples()]
        for i, fut in enumerate(as_completed(futures), start=1):
            cid, parsed, from_cache, errs = fut.result()
            results[cid] = parsed
            if errs:
                warnings.append((cid, errs))
            top = max(parsed["scores"].values())
            flag = "  (consistency warning)" if errs else ""
            print(f"  [{i}/{len(selected)}] [{'cached' if from_cache else 'fresh'}] "
                  f"{cid}: max score {top}{flag}")

    if warnings:
        log = project.logs_dir / f"topics_{sset}_validation_warnings.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "a") as f:
            for cid, errs in warnings:
                f.write(f"# {datetime.now(timezone.utc).isoformat(timespec='seconds')}  {cid}\n")
                for e in errs:
                    f.write(f"  {e}\n")
        print(f"\nNOTE: {len(warnings)} clip(s) had soft consistency warnings; see {log}")
    return results


def _build_frames(selected: pd.DataFrame, results: dict[str, dict], tset: TopicSet,
                  cfg: dict, model: str, reasoning: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    maxv = max(int(v) for v in cfg["score_values"])   # top score = "does belong"
    tids = tset.ids
    name_by_id = {t["id"]: t["name"] for t in tset.topics}
    wide_rows, long_rows = [], []
    for row in selected.itertuples():
        cid, iid = row.clip_id, row.interview_id
        parsed = results[cid]
        scores = parsed["scores"]
        just = {e["topic_id"]: e["justification"] for e in parsed.get("evidence", [])}
        for tid in tids:
            long_rows.append({"clip_id": cid, "interview_id": iid, "topic_id": tid,
                              "topic_name": name_by_id[tid], "score": int(scores[tid]),
                              "justification": just.get(tid, "")})
        top = max(scores.values())
        wide = {"clip_id": cid, "interview_id": iid}
        wide.update({tid: int(scores[tid]) for tid in tids})
        wide["top_score"] = int(top)
        wide["top_topics"] = "|".join(tid for tid in tids if scores[tid] == top) if top > 0 else ""
        wide["n_topics_assigned"] = sum(1 for tid in tids if scores[tid] == maxv)
        wide["fits_any"] = top == maxv
        wide["model"] = model
        wide["reasoning_effort"] = reasoning
        wide_rows.append(wide)
    return pd.DataFrame(wide_rows), pd.DataFrame(long_rows)


def _print_distribution(this: pd.DataFrame, tset: TopicSet, cfg: dict) -> None:
    """Compact score-distribution audit over this run's clips (the review-worthy numbers)."""
    maxv = max(int(v) for v in cfg["score_values"])
    print(f"\nClips: {len(this)}  | fit >=1 topic at score {maxv}: {int(this['fits_any'].sum())} "
          f"({100 * this['fits_any'].mean():.0f}%)  | mean topics assigned: "
          f"{this['n_topics_assigned'].mean():.2f}")
    print(f"Per-topic clips assigned (score {maxv}):")
    for tid in tset.ids:
        print(f"  {tid:<24} {int((this[tid] == maxv).sum()):>4}")


# --- review md ------------------------------------------------------------------------------

def _write_demo_md(project: Project, sset: str, selected: pd.DataFrame, texts: dict[str, str],
                   results: dict[str, dict], tset: TopicSet, model: str, reasoning: str):
    name_by_id = {t["id"]: t["name"] for t in tset.topics}
    diag_dir = project.diags_dir / "topics"
    diag_dir.mkdir(parents=True, exist_ok=True)
    lines = [f"# Topic tags — set '{sset}' — DEMO", "",
             f"{len(selected)} clips · model `{model}` · reasoning `{reasoning}`", ""]
    for row in selected.itertuples():
        parsed = results[row.clip_id]
        scores = parsed["scores"]
        just = {e["topic_id"]: e["justification"] for e in parsed.get("evidence", [])}
        lines += [f"## {row.clip_id}", "",
                  f"*{row.interview_id} · paragraphs {int(row.start_paragraph_idx)}–"
                  f"{int(row.end_paragraph_idx)} · {int(row.total_words)} words*", ""]
        hits = sorted((tid for tid in tset.ids if scores[tid] >= 1),
                      key=lambda t: (-scores[t], t))
        if hits:
            lines.append("**Topics:**")
            for tid in hits:
                j = str(just.get(tid, "")).strip()
                lines.append(f"- **{scores[tid]}** · {name_by_id[tid]} (`{tid}`)"
                             + (f" — {j}" if j else ""))
        else:
            lines.append("**Topics:** _(none — clip fits no listed topic)_")
        lines += ["", "```", texts[row.clip_id].rstrip("\n"), "```", ""]
    path = diag_dir / f"{sset}_demo.md"
    path.write_text("\n".join(lines))
    return path


# --- preview --------------------------------------------------------------------------------

def _est_tokens(text: str) -> int:
    return int(round(len(text.split()) * 1.3))


def preview_call(project: Project, set_name: str | None = None,
                 clip_id: str | None = None) -> None:
    """Print the EXACT request for one clip — instructions, schema, user content — no API call.
    Mirrors a demo call (justifications on), since the demo is what runs next. Use it to review
    the assembled prompt + taxonomy before spending anything."""
    cfg, tset, _, instructions, _ = _context(project, set_name, justify=None, demo=True)
    score_values = tuple(int(v) for v in cfg["score_values"])
    schema = build_schema(build_scores_model(tset.ids, score_values=score_values, justify=True),
                          "topic_scores")

    clips_df = load_clips(project)
    if clip_id is None:
        clip_id = sample_clips_spread(clips_df, 1, int(cfg["demo_seed"]))[0]  # first demo clip
    row = clips_df[clips_df["clip_id"] == clip_id]
    if row.empty:
        raise ToolkitError(f"clip_id {clip_id!r} not found in the clips deliverable")
    row = row.iloc[0]
    para = paragraphs_by_interview(load_paragraphs(project))[row["interview_id"]]
    user_content = render_clip_plain(clip_id, int(row["start_paragraph_idx"]),
                                     int(row["end_paragraph_idx"]), para)

    schema_json = json.dumps(schema, indent=2)
    bar = "=" * 90
    print(bar + "\nINSTRUCTIONS (stable, cached prefix)\n" + bar)
    print(instructions)
    print(bar + "\ntext.format  (json schema — also part of the cached prefix)\n" + bar)
    print(schema_json)
    print(bar + f"\nINPUT  (variable, uncached) — clip {clip_id}\n" + bar)
    print(user_content)
    print(bar + "\nTOKEN BREAKDOWN (rough, ~1.3 tokens/word)\n" + bar)
    ti, ts, tc = _est_tokens(instructions), _est_tokens(schema_json), _est_tokens(user_content)
    print(f"  instructions prefix : ~{ti:>6,} tokens   (cached after first call)")
    print(f"  schema              : ~{ts:>6,} tokens   (cached)")
    print(f"  --> cached prefix   : ~{ti + ts:>6,} tokens")
    print(f"  clip (this one)     : ~{tc:>6,} tokens   (fresh every call)")
    print(f"  TOTAL input         : ~{ti + ts + tc:>6,} tokens")
