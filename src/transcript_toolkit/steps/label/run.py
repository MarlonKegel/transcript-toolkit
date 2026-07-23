"""`toolkit label` — one short Labeler-style label per clip.

Consumes the clip boundaries produced by `toolkit clip` and, per interview, batches several
CONSECUTIVE clips into one LLM call (with the immediately-preceding and -following clips shown
as read-only context), getting one label back per clip. An optional workspace addendum
(config `label.addendum`) appends project-specific consistency rules to the prompt.

Demo-first: `--demo` labels the persisted `toolkit sample` interviews and writes the annotated
review pages only; a full run is demo-gated, confirms cost, writes
outputs/labels/labels.{parquet,csv} and the review pages (diags/label/*.html). A failed batch fails
its whole interview (logged to logs/label_validation.log) — never partial labels.
Idempotent + resumable via the per-batch cache (.toolkit/cache/label.jsonl).
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from threading import Lock

import pandas as pd
from pydantic import BaseModel

from ...core import cost as costmod
from ...core.cache import JsonlAppender, cache_key, latest_records
from ...core.config import load_step_config, require
from ...core.console import confirm_or_abort, reveal
from ...core.llm import build_schema, call_llm, check_levels, openai_client
from ...core.render import format_paragraph_full
from ...core.sampling import load_interview_sample
from ...core.tables import load_clips, load_paragraphs, merge_subset, paragraphs_by_interview, write_deliverable
from ...errors import ToolkitError
from ...project import Project
from ...state import check_demo_gate, record_demo, record_full
from ..clip.chunking import estimate_paragraph_tokens
from ..clip.run import _estimate, _log_failures, effective_timestamp
from ..summarize import load_prompt
from .annotate import write_annotated
from .batching import LabelBatch, batch_clips

STEP = "label"

# Separator between the base prompt and the optional project-specific addendum.
# Stable on purpose: it is part of the LLM input and the cache_key, so changing
# it would silently invalidate every cached label.
ADDENDUM_SEP = "\n\n## Project-specific consistency rules\n\n"


class ClipLabel(BaseModel):
    clip_number: int
    label: str


class BatchLabels(BaseModel):
    labels: list[ClipLabel]


# --- model-facing rendering (BYTE-STABLE: feeds cache keys) -----------------------------------

def _indexed_paragraph_line(r) -> str:
    """paragraph_line for a paragraph_idx-indexed frame row (the idx lives in r.Index)."""
    ts = effective_timestamp(r.turn_time_start, r.sub_time_start)
    return format_paragraph_full(int(r.Index), ts, r.speaker_role, int(r.word_count), r.speech)


def _clip_lines(clip_id: str, start: int, end: int, para_indexed: pd.DataFrame) -> list[str]:
    sub = para_indexed.loc[start:end]
    expected = end - start + 1
    if len(sub) != expected:
        raise ToolkitError(
            f"clip {clip_id}: expected {expected} paragraphs in [{start}, {end}], got {len(sub)} "
            f"(clips/paragraphs version skew? re-run `toolkit clip` after the last `toolkit import`)")
    return [_indexed_paragraph_line(r) for r in sub.itertuples()]


def compute_clip_tokens(clips_by_id: dict[str, tuple[int, int]], para_indexed: pd.DataFrame) -> dict[str, int]:
    out: dict[str, int] = {}
    for cid, (start, end) in clips_by_id.items():
        sub = para_indexed.loc[start:end]
        out[cid] = sum(estimate_paragraph_tokens(int(w)) for w in sub["word_count"])
    return out


def build_batch_user_content(batch: LabelBatch, clips_by_id: dict[str, tuple[int, int]],
                             para_indexed: pd.DataFrame) -> str:
    lines: list[str] = []

    def emit(header: str, cid: str) -> None:
        start, end = clips_by_id[cid]
        lines.append(header)
        lines.append("")
        lines.extend(_clip_lines(cid, start, end, para_indexed))
        lines.append("")

    if batch.prev_clip_id is not None:
        emit("## PREVIOUS CLIP (context only — do NOT label)", batch.prev_clip_id)
    for n, cid in enumerate(batch.clip_ids, start=1):
        emit(f"## CLIP {n}", cid)
    if batch.next_clip_id is not None:
        emit("## NEXT CLIP (context only — do NOT label)", batch.next_clip_id)

    return "\n".join(lines).rstrip() + "\n"


# --- validation ----------------------------------------------------------------------------------

def validate_batch(parsed: BatchLabels, batch: LabelBatch) -> list[str]:
    """Hard checks: count matches, clip_number set == {1..K}, no empty labels."""
    errs: list[str] = []
    k = len(batch.clip_ids)
    nums = [s.clip_number for s in parsed.labels]
    if len(nums) != k:
        errs.append(f"returned {len(nums)} labels, expected {k}")
    if sorted(nums) != list(range(1, k + 1)):
        errs.append(f"clip_number set {sorted(nums)} != 1..{k}")
    for s in parsed.labels:
        if not s.label.strip():
            errs.append(f"clip_number {s.clip_number}: empty label")
    return errs


# --- run -----------------------------------------------------------------------------------------

def _load_addendum(project: Project, rel_path: str) -> str:
    path = project.root / rel_path
    if not path.exists():
        raise ToolkitError(f"Configured label addendum not found: {path} "
                           f"(set `addendum: null` in config.yaml to disable it).")
    return path.read_text().strip()


def _context(project: Project):
    cfg = load_step_config(project, STEP)
    require(cfg, ["model", "reasoning", "verbosity", "prompt", "batch_threshold_tokens",
                  "max_workers"], STEP)
    check_levels(cfg["reasoning"], cfg["verbosity"])
    instructions = load_prompt(project, cfg["prompt"])
    if cfg.get("addendum"):
        instructions = instructions + ADDENDUM_SEP + _load_addendum(project, cfg["addendum"])
    fingerprint = cache_key(cfg["model"], cfg["reasoning"], cfg["verbosity"], instructions,
                            str(cfg["batch_threshold_tokens"]))
    return cfg, instructions, fingerprint


def _plan_interview(iid: str, clips_df: pd.DataFrame, para_indexed: pd.DataFrame,
                    batch_threshold: int) -> tuple[list[str], list[LabelBatch], list[str]]:
    """(ordered_clip_ids, batches, per-batch user_content) for one interview — fully
    deterministic given the clips table, so cache keys are computable up front."""
    clips = clips_df[clips_df["interview_id"] == iid].sort_values("start_paragraph_idx")
    ordered_clip_ids = clips["clip_id"].tolist()
    assert "procedural" not in set(ordered_clip_ids), f"{iid}: 'procedural' present in clips table"
    clips_by_id = {c.clip_id: (int(c.start_paragraph_idx), int(c.end_paragraph_idx))
                   for c in clips.itertuples()}
    clip_tokens = compute_clip_tokens(clips_by_id, para_indexed)
    batches = batch_clips(iid, ordered_clip_ids, clip_tokens, batch_threshold)
    contents = [build_batch_user_content(b, clips_by_id, para_indexed) for b in batches]
    return ordered_clip_ids, batches, contents


def _label_interview(iid: str, plan, cache: dict, cache_lock: Lock, appender: JsonlAppender,
                     client, cfg: dict, instructions: str, fingerprint: str, schema: dict) -> dict:
    """All batch calls for one interview. On any hard validation/coverage error the whole
    interview fails (empty maps) so partial labels are never emitted silently."""
    model, reasoning, verbosity = cfg["model"], cfg["reasoning"], cfg["verbosity"]
    ordered_clip_ids, batches, contents = plan
    prompt_cache_key_str = cache_key(model, reasoning, verbosity, instructions)

    label_map: dict[str, str] = {}
    batch_of: dict[str, int] = {}
    aggregate_usage = {"input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0, "cached_input_tokens": 0}
    all_from_cache = True
    all_errs: list[str] = []

    for batch, user_content in zip(batches, contents):
        ck = cache_key(model, reasoning, verbosity, instructions, user_content)
        with cache_lock:
            cached = cache.get(ck)

        if cached is not None:
            parsed = BatchLabels(labels=[ClipLabel(**s) for s in cached["labels"]])
            usage = cached["usage"]
        else:
            raw, usage = call_llm(client, model, reasoning, verbosity, schema,
                                  instructions, user_content, prompt_cache_key_str,
                                  poll_interval_s=float(cfg.get("poll_interval_s", 4)),
                                  max_total_wait_s=float(cfg.get("max_total_wait_s", 1800)))
            parsed = BatchLabels.model_validate(raw)
            record = {
                "cache_key": ck, "fingerprint": fingerprint,
                "interview_id": iid, "batch_idx": batch.batch_idx,
                "clip_ids": batch.clip_ids, "prev_clip_id": batch.prev_clip_id,
                "next_clip_id": batch.next_clip_id, "est_tokens": batch.est_tokens,
                "labels": [s.model_dump() for s in parsed.labels],
                "model": model, "reasoning_effort": reasoning, "verbosity": verbosity,
                "usage": usage, "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            appender.append(record)
            with cache_lock:
                cache[ck] = record
            all_from_cache = False

        errs = validate_batch(parsed, batch)
        if errs:
            all_errs.extend([f"batch {batch.batch_idx}: {e}" for e in errs])
        else:
            by_num = {s.clip_number: s.label.strip() for s in parsed.labels}
            for n, cid in enumerate(batch.clip_ids, start=1):
                label_map[cid] = by_num[n]
                batch_of[cid] = batch.batch_idx

        for k in aggregate_usage:
            aggregate_usage[k] += usage.get(k) or 0

    if not all_errs and set(label_map) != set(ordered_clip_ids):
        missing = sorted(set(ordered_clip_ids) - set(label_map))
        all_errs.append(f"coverage: {len(missing)} clip(s) unlabeled: {missing[:10]}")

    if all_errs:
        label_map, batch_of = {}, {}
    return {"label_map": label_map, "batch_of": batch_of, "n_clips": len(ordered_clip_ids),
            "errs": all_errs, "usage": aggregate_usage, "all_from_cache": all_from_cache}


def run_label(project: Project, demo: bool = False, interviews: list[str] | None = None,
              yes: bool = False, skip_demo_check: bool = False) -> pd.DataFrame:
    if demo and interviews:
        raise ToolkitError("--demo and --interview are mutually exclusive.")
    cfg, instructions, fingerprint = _context(project)
    clips_df = load_clips(project)
    paragraphs_df = load_paragraphs(project)
    paras_clipped_path = project.outputs_dir / "clips" / "paragraphs_clipped.parquet"
    if not paras_clipped_path.exists():
        raise ToolkitError(f"{paras_clipped_path} not found. Run `toolkit clip` first.")
    available = sorted(clips_df["interview_id"].unique())

    if demo:
        keys = load_interview_sample_checked(project, available)
    elif interviews:
        keys = sorted(interviews)
        unknown = [k for k in keys if k not in available]
        if unknown:
            raise ToolkitError(f"Unknown interview id(s) (no clips): {', '.join(unknown)}. "
                               f"Available: {', '.join(available)}")
    else:
        keys = available

    model, reasoning = cfg["model"], cfg["reasoning"]
    batch_threshold = int(cfg["batch_threshold_tokens"])
    para_by_iid = paragraphs_by_interview(paragraphs_df)
    plans = {iid: _plan_interview(iid, clips_df, para_by_iid[iid], batch_threshold) for iid in keys}

    cache_path = project.cache_dir / "label.jsonl"
    cache = latest_records(cache_path, "cache_key")
    verbosity = cfg["verbosity"]
    all_cks = [cache_key(model, reasoning, verbosity, instructions, uc)
               for iid in keys for uc in plans[iid][2]]
    n_total = len(all_cks)
    n_cached = sum(1 for ck in all_cks if ck in cache)
    n_fresh = n_total - n_cached

    if not demo:
        check_demo_gate(project, STEP, fingerprint,
                        demo_command="toolkit label --demo", skip=skip_demo_check)
        estimate = _estimate(cache, fingerprint, model, n_fresh)
        confirm_or_abort(
            f"Label {len(keys)} interview(s) with {model} "
            f"({n_cached} of {n_total} batch calls cached, {n_fresh} fresh API calls{estimate})?", yes)

    print(f"Labeling {len(keys)} interview(s) · {model}/{reasoning} · "
          f"batch threshold {batch_threshold} tokens, +read-only prev/next neighbour clip · "
          f"addendum {'on' if cfg.get('addendum') else 'off'} · "
          f"{n_cached} cached / {n_fresh} fresh batch calls")

    client = openai_client(project.root) if n_fresh else None
    appender = JsonlAppender(cache_path)
    lock = Lock()
    schema = build_schema(BatchLabels, "BatchLabels")

    results: dict[str, dict] = {}
    failed: list[tuple[str, list[str]]] = []

    def work(iid: str):
        return iid, _label_interview(iid, plans[iid], cache, lock, appender, client,
                                     cfg, instructions, fingerprint, schema)

    with ThreadPoolExecutor(max_workers=int(cfg["max_workers"])) as ex:
        futures = [ex.submit(work, iid) for iid in keys]
        for i, fut in enumerate(as_completed(futures), start=1):
            iid, res = fut.result()
            results[iid] = res
            tag = "cached" if res["all_from_cache"] else "fresh"
            if res["errs"]:
                print(f"  [{i}/{len(keys)}] [{tag}] {iid}: VALIDATION FAILED ({len(res['errs'])} error(s))")
                for e in res["errs"]:
                    print(f"      - {e}")
                failed.append((iid, res["errs"]))
            else:
                print(f"  [{i}/{len(keys)}] [{tag}] {iid}: labeled {res['n_clips']} clips")

    log_path = _log_failures(project, failed, "label_validation.log") if failed else None

    ok = [iid for iid in keys if not results[iid]["errs"]]
    label_by_id = {cid: lbl for iid in ok for cid, lbl in results[iid]["label_map"].items()}
    batch_by_id = {cid: b for iid in ok for cid, b in results[iid]["batch_of"].items()}

    deliver = clips_df[clips_df["interview_id"].isin(ok)].drop(columns=["model", "reasoning_effort"]).copy()
    deliver["label"] = deliver["clip_id"].map(label_by_id)
    deliver["batch_idx"] = deliver["clip_id"].map(batch_by_id)
    deliver["model"] = model
    deliver["reasoning_effort"] = reasoning
    if len(deliver):
        assert deliver["label"].notna().all(), "internal error: unmapped clip in delivered table"
        assert (deliver["label"].str.strip() != "").all(), "internal error: empty label in delivered table"

    paras_clipped = pd.read_parquet(paras_clipped_path)
    diag_dir = write_annotated(project, ok, paras_clipped, clips_df, label_by_id)

    if demo:
        if failed:
            raise ToolkitError(
                f"{len(failed)} demo interview(s) failed label validation: "
                f"{', '.join(iid for iid, _ in failed)}. Details in {log_path}. "
                f"Demo not recorded; adjust config/prompts and re-run `toolkit label --demo`.")
        record_demo(project, STEP, fingerprint, units=keys, diag=str(diag_dir))
        print(f"\nDemo review files: open {diag_dir}/index.html")
        print("Review them; adjust config.yaml / prompts/ and re-demo if needed. "
              "Then run `toolkit label` for the full corpus.")
        reveal(diag_dir / "index.html")
        return deliver

    labels_out = deliver
    if ok:
        out_path = project.outputs_dir / "labels" / "labels.parquet"
        # A subset or partially-failed run splices its interviews into the existing table.
        if (interviews or failed) and out_path.exists():
            labels_out = merge_subset(pd.read_parquet(out_path), deliver, "interview_id")
        write_deliverable(labels_out, out_path, sort_by="clip_id")
        print(f"\nWrote {len(labels_out)} clip labels ({len(ok)} interview(s)) -> {out_path}")
        print(f"Review files: open {diag_dir}/index.html")
        _print_style_audit(deliver)

    if not interviews and not failed:
        record_full(project, STEP, fingerprint, model=model, n_units=len(keys))
    if failed:
        raise ToolkitError(
            f"{len(failed)} interview(s) failed label validation: "
            f"{', '.join(iid for iid, _ in failed)}. Details in {log_path}. "
            f"Successful interviews were written; re-run `toolkit label` to retry the failed ones.")
    return labels_out


def load_interview_sample_checked(project: Project, available: list[str]) -> list[str]:
    keys = load_interview_sample(project)
    unknown = [k for k in keys if k not in available]
    if unknown:
        raise ToolkitError(f"Demo sample interview(s) have no clips: {', '.join(unknown)}. "
                           f"Re-run `toolkit clip` (or `toolkit sample`) first.")
    return keys


def _print_style_audit(deliver: pd.DataFrame) -> None:
    """Labeler adherence + duplicates, to guide prompt iteration."""
    if not len(deliver):
        return
    lens = deliver["label"].str.len()
    over = int((lens > 120).sum())
    trailing = int(deliver["label"].str.rstrip().str.endswith(".").sum())
    dups = int(deliver.groupby("interview_id")["label"].apply(lambda s: s.duplicated().sum()).sum())
    print("\n=== Label style audit ===")
    print(f"Length (chars): mean={lens.mean():.0f}  median={lens.median():.0f}  "
          f"max={int(lens.max())}  >120: {over}")
    print(f"Trailing period: {trailing}   Intra-interview duplicate labels: {dups}")


# --- batch preview (read-only, no API) -------------------------------------------------------------

def preview_batches(project: Project) -> None:
    """Print how each interview's clips group into label batches under the current config."""
    cfg = load_step_config(project, STEP)
    require(cfg, ["batch_threshold_tokens"], STEP)
    threshold = int(cfg["batch_threshold_tokens"])
    clips_df = load_clips(project)
    para_by_iid = paragraphs_by_interview(load_paragraphs(project))

    rows = []
    for iid in sorted(clips_df["interview_id"].unique()):
        ordered, batches, _contents = _plan_interview(iid, clips_df, para_by_iid[iid], threshold)
        # Partition check: every clip labeled exactly once across batches.
        labeled = [cid for b in batches for cid in b.clip_ids]
        assert labeled == ordered, f"{iid}: batches do not partition clips in order"
        rows.append({"interview_id": iid, "n_clips": len(ordered),
                     "tot_tokens": sum(b.est_tokens for b in batches),
                     "n_batches": len(batches), "batches": batches})
    rows.sort(key=lambda r: -r["tot_tokens"])

    print(f"=== Clip-batch preview (threshold={threshold}) ===")
    print()
    print(f"{'interview_id':<42} {'clips':>6} {'tot_tok':>8} {'n_b':>4}  layout [n_clips|~tok|prev->next]")
    print("-" * 140)
    for r in rows:
        layout = "  ".join(
            f"[{len(b.clip_ids)}c|~{b.est_tokens // 1000}.{(b.est_tokens % 1000) // 100}k|"
            f"{(b.prev_clip_id or '-').split('_')[-1]}->{(b.next_clip_id or '-').split('_')[-1]}]"
            for b in r["batches"])
        print(f"{r['interview_id']:<42} {r['n_clips']:>6} {r['tot_tokens']:>8,} {r['n_batches']:>4}  {layout}")

    by_n: dict[int, int] = {}
    for r in rows:
        by_n[r["n_batches"]] = by_n.get(r["n_batches"], 0) + 1
    print()
    print(f"Batch-count distribution across {len(rows)} interviews:")
    for n_b, count in sorted(by_n.items()):
        print(f"  {n_b} batch(es): {count} interview(s)")
    bsizes = [len(b.clip_ids) for r in rows for b in r["batches"]]
    if bsizes:
        print()
        print(f"Clips per batch: min={min(bsizes)}  mean={sum(bsizes) / len(bsizes):.1f}  max={max(bsizes)}")
