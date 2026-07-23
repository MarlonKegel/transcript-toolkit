"""`toolkit clip` — segment each interview into topically-coherent clips.

One structured-output LLM call per chunk: interviews estimated under `chunk_threshold_tokens`
run as a single call; longer ones split into balanced chunks with a locked-context + redecide
overlap at each seam. Chunks within an interview run sequentially (each chunk N>=1 needs the
previous chunk's output for its locked-context preamble); interviews run in parallel.

Demo-first: `--demo` clips the persisted `toolkit sample` interviews and writes the annotated
review pages only; a full run is demo-gated, confirms cost, writes
outputs/clips/{clips,paragraphs_clipped}.{parquet,csv} and the review pages (diags/clip/*.html).
Every chunk's output is validated for exact decision-region coverage; a failed interview is
logged to logs/clip_validation.log and never written. Idempotent + resumable via the per-chunk
cache (.toolkit/cache/clip.jsonl).
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
from ...core.tables import load_paragraphs, merge_subset, write_deliverable
from ...errors import ToolkitError
from ...project import Project
from ...state import check_demo_gate, record_demo, record_full
from ..summarize import load_prompt
from .annotate import write_annotated
from .chunking import CHUNK_OVERHEAD_BASE, Chunk, chunk_paragraphs, estimate_paragraph_tokens, ts_to_seconds

STEP = "clip"


class Clip(BaseModel):
    start_paragraph_idx: int
    end_paragraph_idx: int


class ChunkSegmentation(BaseModel):
    clips: list[Clip]
    procedural_paragraph_idxs: list[int]


# --- model-facing rendering (BYTE-STABLE: feeds cache keys) -----------------------------------

def effective_timestamp(turn_time_start: str, sub_time_start: str) -> str:
    return sub_time_start if sub_time_start else turn_time_start


def paragraph_line(row) -> str:
    """One full paragraph line for a paragraphs-table row (itertuples row)."""
    ts = effective_timestamp(row.turn_time_start, row.sub_time_start)
    return format_paragraph_full(int(row.paragraph_idx), ts, row.speaker_role,
                                 int(row.word_count), row.speech)


def build_user_content(chunk: Chunk, paragraphs_df: pd.DataFrame) -> str:
    """Render a chunk-0 (or single-chunk) input: plain numbered paragraph list."""
    if not chunk.is_first:
        raise ValueError("build_user_content is for chunk 0 only; use build_chunked_user_content for chunks >= 1")
    lines: list[str] = []
    for r in paragraphs_df.sort_values("paragraph_idx").itertuples():
        idx = int(r.paragraph_idx)
        if idx < chunk.shown_start or idx > chunk.shown_end:
            continue
        lines.append(paragraph_line(r))
    return "\n".join(lines)


def compute_locked_assignments(prev_seg_clips: list[Clip], prev_seg_procedural: list[int],
                               locked_lo: int, locked_hi: int) -> dict[int, str | int]:
    """For each paragraph in [locked_lo, locked_hi], return its clip index (1-based)
    in prev_seg_clips, or 'procedural'."""
    proc_set = set(prev_seg_procedural)
    out: dict[int, str | int] = {}
    for idx in range(locked_lo, locked_hi + 1):
        if idx in proc_set:
            out[idx] = "procedural"
            continue
        for ci, clip in enumerate(prev_seg_clips, start=1):
            if clip.start_paragraph_idx <= idx <= clip.end_paragraph_idx:
                out[idx] = ci
                break
    return out


def build_chunked_user_content(chunk: Chunk, paragraphs_df: pd.DataFrame,
                               prev_seg_clips: list[Clip], prev_seg_procedural: list[int]) -> str:
    """Render a chunk-N (N >= 1) input: locked-context preamble + paragraphs with inline markers."""
    locked_lo, locked_hi = chunk.shown_start, chunk.decision_start - 1
    locked_assignment = compute_locked_assignments(prev_seg_clips, prev_seg_procedural, locked_lo, locked_hi)

    # Assign labels A, B, C, ... in order of first appearance in locked region.
    clip_label: dict[int, str] = {}
    nxt = ord("A")
    for idx in range(locked_lo, locked_hi + 1):
        a = locked_assignment.get(idx)
        if not isinstance(a, int):
            continue
        if a not in clip_label:
            clip_label[a] = chr(nxt)
            nxt += 1
    clip_true_start = {n: prev_seg_clips[n - 1].start_paragraph_idx for n in clip_label}

    lines: list[str] = []
    lines.append("## Continuing context from the previous chunk")
    lines.append("")
    lines.append(
        f"Paragraphs {locked_lo} to {locked_hi} are LOCKED — they have already been assigned in the "
        f"previous chunk and you cannot change those assignments."
    )
    lines.append("")
    lines.append("Inline marker lines indicate the locked clip boundaries:")
    lines.append("- `CLIP X, cont. [LOCKED]` — the locked clip X continues from the previous chunk into this one (its true start is before the locked region).")
    lines.append("- `CLIP X STARTS [LOCKED]` — locked clip X starts at the paragraph immediately below this marker.")
    lines.append("- `PROCEDURAL [LOCKED]` — the paragraph immediately below this marker is procedural and excluded from any clip.")
    lines.append(
        f"- `DECISION REGION STARTS` — separates the locked region from the decision region. The paragraph "
        f"immediately below this marker (paragraph {chunk.decision_start}) is the first one you must decide on."
    )
    lines.append("")
    lines.append(
        f"Segment paragraphs from {chunk.decision_start} onwards. To extend a locked clip into your decision "
        f"region, emit a clip whose `start_paragraph_idx` equals the paragraph index immediately below that "
        f"locked clip's first marker in the input (i.e. the locked clip's first locked paragraph). "
        f"Otherwise, all your clips must have `start_paragraph_idx >= {chunk.decision_start}`."
    )
    lines.append("")
    lines.append("## Paragraphs")
    lines.append("")

    prev_assignment = None
    for r in paragraphs_df.sort_values("paragraph_idx").itertuples():
        idx = int(r.paragraph_idx)
        if idx < chunk.shown_start or idx > chunk.shown_end:
            continue
        if idx == chunk.decision_start and locked_lo <= locked_hi:
            lines.append("DECISION REGION STARTS")
        if idx <= locked_hi:
            a = locked_assignment.get(idx)
            if a != prev_assignment:
                if a == "procedural":
                    lines.append("PROCEDURAL [LOCKED]")
                elif isinstance(a, int):
                    label = clip_label[a]
                    true_start = clip_true_start[a]
                    if prev_assignment is None and true_start < locked_lo:
                        lines.append(f"CLIP {label}, cont. [LOCKED]")
                    elif true_start == idx:
                        lines.append(f"CLIP {label} STARTS [LOCKED]")
                    else:
                        lines.append(f"CLIP {label}, cont. [LOCKED]")
                prev_assignment = a
            lines.append(paragraph_line(r))
        else:
            prev_assignment = None
            lines.append(paragraph_line(r))
    return "\n".join(lines)


# --- stitching + validation --------------------------------------------------------------------

def stitch_chunks(chunk_outputs: list[tuple[Chunk, ChunkSegmentation]]) -> tuple[list[Clip], list[int]]:
    """Merge per-chunk clips/procedural into the final interview-level output.

    Rules:
    - For non-last chunks: discard clips entirely in throwaway zone (start > owned_end);
      truncate clips that straddle (end > owned_end → end := owned_end).
    - When a later chunk's first clip starts in the previous chunk's owned region
      (i.e. extending a locked clip), replace the matching previous final clip with
      the extended one.
    - Procedural set: union, restricted to each chunk's owned region.
    """
    final_clips: list[Clip] = []
    procedural: set[int] = set()

    for ci, (chunk, seg) in enumerate(chunk_outputs):
        is_last = ci == len(chunk_outputs) - 1
        own_start, own_end = chunk.owned_start, chunk.owned_end
        clips = sorted(seg.clips, key=lambda c: c.start_paragraph_idx)

        # Handle "extending" clip (must be the first; only one allowed).
        # The extension continues the previous chunk's last clip (the one at the seam). The prompt
        # tells the model to start the extension at that clip's FIRST VISIBLE locked paragraph, so
        # a valid extension start is either:
        #   - the previous clip's true start        (the clip began inside this chunk's overlap), or
        #   - this chunk's shown_start               (the clip continued in from before the overlap,
        #                                             so its true start isn't visible to the model).
        # Either way we keep the previous clip's TRUE start and extend its end. Any other start is a
        # genuine inconsistency and still fails.
        if clips and clips[0].start_paragraph_idx < own_start:
            ext = clips[0]
            clips = clips[1:]
            prev = final_clips[-1] if final_clips else None
            anchors_prev_start = prev is not None and ext.start_paragraph_idx == prev.start_paragraph_idx
            anchors_shown_start = (
                prev is not None and ext.start_paragraph_idx == chunk.shown_start
                and prev.start_paragraph_idx <= chunk.shown_start <= prev.end_paragraph_idx)
            if anchors_prev_start or anchors_shown_start:
                new_end = min(ext.end_paragraph_idx, own_end) if not is_last else ext.end_paragraph_idx
                final_clips[-1] = Clip(start_paragraph_idx=prev.start_paragraph_idx,
                                       end_paragraph_idx=max(prev.end_paragraph_idx, new_end))
            else:
                raise RuntimeError(
                    f"chunk {chunk.chunk_idx}: extending clip start={ext.start_paragraph_idx} matches "
                    f"neither the previous final clip's start nor this chunk's shown_start="
                    f"{chunk.shown_start} (last final was {prev})"
                )

        for clip in clips:
            if not is_last and clip.start_paragraph_idx > own_end:
                continue  # throwaway zone
            new_end = min(clip.end_paragraph_idx, own_end) if not is_last else clip.end_paragraph_idx
            final_clips.append(Clip(start_paragraph_idx=clip.start_paragraph_idx, end_paragraph_idx=new_end))

        for pidx in seg.procedural_paragraph_idxs:
            if own_start <= pidx <= own_end:
                procedural.add(pidx)

    return final_clips, sorted(procedural)


def validate_chunk_coverage(seg: ChunkSegmentation, chunk: Chunk) -> list[str]:
    """Coverage check scoped to the chunk's decision region.

    For chunk 0 / single-chunk: decision region == shown range. Every paragraph
    in [shown_start, shown_end] must appear in exactly one clip or in procedural.
    For chunks >= 1: coverage applies to [decision_start, shown_end] only; the
    locked region [shown_start, decision_start - 1] is not the model's responsibility.
    """
    errs: list[str] = []
    decision_idxs = set(range(chunk.decision_start, chunk.shown_end + 1))
    procedural = set(seg.procedural_paragraph_idxs)
    covered: set[int] = set()
    # last_end starts at shown_start - 1 so the first clip can validly start in
    # the locked region (extending a locked clip from the previous chunk).
    last_end = chunk.shown_start - 1
    for i, clip in enumerate(seg.clips):
        if clip.start_paragraph_idx > clip.end_paragraph_idx:
            errs.append(f"Clip {i}: start ({clip.start_paragraph_idx}) > end ({clip.end_paragraph_idx})")
            continue
        if clip.start_paragraph_idx <= last_end:
            errs.append(f"Clip {i}: starts at {clip.start_paragraph_idx} but previous clip ended at {last_end} (not ordered or overlapping)")
        clip_idxs = set(range(clip.start_paragraph_idx, clip.end_paragraph_idx + 1))
        overlap_with_proc = clip_idxs & procedural
        if overlap_with_proc:
            errs.append(f"Clip {i}: overlaps with procedural at {sorted(overlap_with_proc)}")
        overlap_with_prev = clip_idxs & covered
        if overlap_with_prev:
            errs.append(f"Clip {i}: overlaps with a previous clip at {sorted(overlap_with_prev)}")
        covered |= clip_idxs
        last_end = clip.end_paragraph_idx

    total = covered | procedural
    missing = decision_idxs - total
    extra = total - set(range(chunk.shown_start, chunk.shown_end + 1))
    if missing:
        errs.append(f"Missing paragraph indices in decision region: {sorted(missing)[:20]}{'...' if len(missing) > 20 else ''}")
    if extra:
        errs.append(f"Out-of-range paragraph indices returned: {sorted(extra)[:20]}{'...' if len(extra) > 20 else ''}")
    return errs


# --- per-interview pipeline ----------------------------------------------------------------------

def _seg_from_record(rec: dict) -> ChunkSegmentation:
    return ChunkSegmentation(
        clips=[Clip(**{k: v for k, v in c.items() if k in Clip.model_fields}) for c in rec["clips"]],
        procedural_paragraph_idxs=list(rec["procedural_paragraph_idxs"]),
    )


def _segment_interview(interview_id: str, df_interview: pd.DataFrame, cache: dict, cache_lock: Lock,
                       appender: JsonlAppender, client, cfg: dict, instructions: str,
                       fingerprint: str, schema: dict) -> dict:
    """One or more sequential chunk calls + stitching for one interview.

    Returns {"mapping", "clip_records", "errs", "usage", "all_from_cache"}; on any validation
    or stitching error the interview yields no clips (never partial output).
    """
    model, reasoning, verbosity = cfg["model"], cfg["reasoning"], cfg["verbosity"]
    chunks = chunk_paragraphs(df_interview, int(cfg["chunk_threshold_tokens"]), int(cfg["overlap_paragraphs"]))
    prompt_cache_key_str = cache_key(model, reasoning, verbosity, instructions)

    chunk_outputs: list[tuple[Chunk, ChunkSegmentation]] = []
    aggregate_usage = {"input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0, "cached_input_tokens": 0}
    all_from_cache = True
    all_errs: list[str] = []

    for chunk in chunks:
        if chunk.is_first:
            user_content = build_user_content(chunk, df_interview)
        else:
            _, prev_seg = chunk_outputs[-1]
            user_content = build_chunked_user_content(
                chunk, df_interview, prev_seg.clips, prev_seg.procedural_paragraph_idxs)
        ck = cache_key(model, reasoning, verbosity, instructions, user_content)

        with cache_lock:
            cached = cache.get(ck)

        if cached is not None:
            seg = _seg_from_record(cached)
            usage = cached["usage"]
        else:
            parsed, usage = call_llm(client, model, reasoning, verbosity, schema,
                                     instructions, user_content, prompt_cache_key_str,
                                     poll_interval_s=float(cfg.get("poll_interval_s", 4)),
                                     max_total_wait_s=float(cfg.get("max_total_wait_s", 1800)))
            seg = ChunkSegmentation.model_validate(parsed)
            record = {
                "cache_key": ck, "fingerprint": fingerprint,
                "interview_id": interview_id, "chunk_idx": chunk.chunk_idx,
                "shown_start": chunk.shown_start, "shown_end": chunk.shown_end,
                "decision_start": chunk.decision_start,
                "owned_start": chunk.owned_start, "owned_end": chunk.owned_end,
                "clips": [c.model_dump() for c in seg.clips],
                "procedural_paragraph_idxs": list(seg.procedural_paragraph_idxs),
                "model": model, "reasoning_effort": reasoning, "verbosity": verbosity,
                "usage": usage, "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            appender.append(record)
            with cache_lock:
                cache[ck] = record
            all_from_cache = False

        errs = validate_chunk_coverage(seg, chunk)
        if errs:
            all_errs.extend([f"chunk {chunk.chunk_idx}: {e}" for e in errs])

        chunk_outputs.append((chunk, seg))
        for k in aggregate_usage:
            aggregate_usage[k] += usage.get(k) or 0

    if all_errs:
        all_clips, all_procedural = [], []
    else:
        try:
            all_clips, all_procedural = stitch_chunks(chunk_outputs)
        except RuntimeError as e:
            all_errs.append(f"stitching failed: {e}")
            all_clips, all_procedural = [], []

    mapping: list[tuple[int, str]] = []
    clip_records: list[dict] = []
    if not all_errs:
        idx_to_row = {int(r.paragraph_idx): r for r in df_interview.itertuples()}
        for n, clip in enumerate(all_clips, start=1):
            clip_id = f"{interview_id}_{n:04d}"
            for pidx in range(clip.start_paragraph_idx, clip.end_paragraph_idx + 1):
                mapping.append((pidx, clip_id))
            rows = [idx_to_row[i] for i in range(clip.start_paragraph_idx, clip.end_paragraph_idx + 1)]
            total_words = sum(int(r.word_count) for r in rows)
            start_ts = effective_timestamp(rows[0].turn_time_start, rows[0].sub_time_start)
            end_ts = effective_timestamp(rows[-1].turn_time_start, rows[-1].sub_time_start)
            start_s = ts_to_seconds(start_ts)
            end_s = ts_to_seconds(end_ts)
            duration_s = (end_s - start_s) if (start_s is not None and end_s is not None) else None
            clip_records.append({
                "interview_id": interview_id,
                "clip_id": clip_id,
                "start_paragraph_idx": clip.start_paragraph_idx,
                "end_paragraph_idx": clip.end_paragraph_idx,
                "n_paragraphs": clip.end_paragraph_idx - clip.start_paragraph_idx + 1,
                "total_words": total_words,
                "start_ts": start_ts,
                "end_ts": end_ts,
                "duration_seconds": duration_s,
                "model": model,
                "reasoning_effort": reasoning,
            })
        for pidx in all_procedural:
            mapping.append((pidx, "procedural"))

    return {"mapping": mapping, "clip_records": clip_records, "errs": all_errs,
            "usage": aggregate_usage, "all_from_cache": all_from_cache}


# --- run -----------------------------------------------------------------------------------------

def _context(project: Project):
    cfg = load_step_config(project, STEP)
    require(cfg, ["model", "reasoning", "verbosity", "prompt", "chunk_threshold_tokens",
                  "overlap_paragraphs", "max_workers"], STEP)
    check_levels(cfg["reasoning"], cfg["verbosity"])
    instructions = load_prompt(project, cfg["prompt"])
    fingerprint = cache_key(cfg["model"], cfg["reasoning"], cfg["verbosity"], instructions,
                            str(cfg["chunk_threshold_tokens"]), str(cfg["overlap_paragraphs"]))
    return cfg, instructions, fingerprint


def _plan_calls(frames: dict[str, pd.DataFrame], cache: dict, cfg: dict, instructions: str) -> tuple[int, int]:
    """(n_cached, n_total) chunk calls for the selected interviews. Chunk N>=1's input depends
    on chunk N-1's output, so only each interview's consecutive prefix of cache hits is
    countable; everything after the first miss counts as fresh."""
    model, reasoning, verbosity = cfg["model"], cfg["reasoning"], cfg["verbosity"]
    n_cached = n_total = 0
    for iid, df_interview in frames.items():
        chunks = chunk_paragraphs(df_interview, int(cfg["chunk_threshold_tokens"]),
                                  int(cfg["overlap_paragraphs"]))
        n_total += len(chunks)
        prev_seg: ChunkSegmentation | None = None
        for chunk in chunks:
            if chunk.is_first:
                user_content = build_user_content(chunk, df_interview)
            else:
                user_content = build_chunked_user_content(
                    chunk, df_interview, prev_seg.clips, prev_seg.procedural_paragraph_idxs)
            rec = cache.get(cache_key(model, reasoning, verbosity, instructions, user_content))
            if rec is None:
                break
            n_cached += 1
            prev_seg = _seg_from_record(rec)
    return n_cached, n_total


def _estimate(cache: dict, fingerprint: str, model: str, n_fresh: int) -> str:
    matching = [r for r in cache.values() if r.get("fingerprint") == fingerprint]
    per = costmod.mean_unit_cost(matching, model)
    if per is None or n_fresh == 0:
        return ""
    return f", ~${per[0] * n_fresh:.2f} est."


def _log_failures(project: Project, failed: list[tuple[str, list[str]]], filename: str):
    log_path = project.logs_dir / filename
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a") as f:
        for iid, errs in failed:
            ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
            f.write(f"# {ts}  {iid}\n")
            for e in errs:
                f.write(f"  {e}\n")
    return log_path


def run_clip(project: Project, demo: bool = False, interviews: list[str] | None = None,
             yes: bool = False, skip_demo_check: bool = False) -> pd.DataFrame:
    if demo and interviews:
        raise ToolkitError("--demo and --interview are mutually exclusive.")
    cfg, instructions, fingerprint = _context(project)
    paragraphs_df = load_paragraphs(project)
    available = sorted(paragraphs_df["interview_id"].unique())

    if demo:
        keys = load_interview_sample(project)
    elif interviews:
        keys = sorted(interviews)
    else:
        keys = available
    unknown = [k for k in keys if k not in available]
    if unknown:
        raise ToolkitError(f"Unknown interview id(s): {', '.join(unknown)}. "
                           f"Available: {', '.join(available)}")

    model, reasoning = cfg["model"], cfg["reasoning"]
    cache_path = project.cache_dir / "clip.jsonl"
    cache = latest_records(cache_path, "cache_key")
    frames = {iid: paragraphs_df[paragraphs_df["interview_id"] == iid] for iid in keys}
    n_cached, n_total = _plan_calls(frames, cache, cfg, instructions)
    n_fresh = n_total - n_cached

    if not demo:
        check_demo_gate(project, STEP, fingerprint,
                        demo_command="toolkit clip --demo", skip=skip_demo_check)
        estimate = _estimate(cache, fingerprint, model, n_fresh)
        confirm_or_abort(
            f"Clip {len(keys)} interview(s) with {model} "
            f"({n_cached} of {n_total} chunk calls cached, {n_fresh} fresh API calls{estimate})?", yes)

    print(f"Clipping {len(keys)} interview(s) · {model}/{reasoning} · "
          f"chunk threshold {cfg['chunk_threshold_tokens']} tokens / overlap "
          f"{cfg['overlap_paragraphs']} paragraphs · {n_cached} cached / {n_fresh} fresh chunk calls")

    client = openai_client(project.root) if n_fresh else None
    appender = JsonlAppender(cache_path)
    lock = Lock()
    schema = build_schema(ChunkSegmentation, "ChunkSegmentation")

    results: dict[str, dict] = {}
    failed: list[tuple[str, list[str]]] = []

    def work(iid: str):
        return iid, _segment_interview(iid, frames[iid], cache, lock, appender, client,
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
                n_proc = len([m for m in res["mapping"] if m[1] == "procedural"])
                print(f"  [{i}/{len(keys)}] [{tag}] {iid}: clips={len(res['clip_records'])} "
                      f"procedural={n_proc}")

    log_path = _log_failures(project, failed, "clip_validation.log") if failed else None

    ok = [iid for iid in keys if not results[iid]["errs"]]
    clips_df = pd.DataFrame([r for iid in ok for r in results[iid]["clip_records"]])
    mapping_df = pd.DataFrame(
        [(iid, pidx, cid) for iid in ok for pidx, cid in results[iid]["mapping"]],
        columns=["interview_id", "paragraph_idx", "clip_id"])
    paras_df = (paragraphs_df[paragraphs_df["interview_id"].isin(ok)]
                .merge(mapping_df, on=["interview_id", "paragraph_idx"], how="left"))

    diag_dir = write_annotated(project, ok, paras_df, clips_df)

    if demo:
        if failed:
            raise ToolkitError(
                f"{len(failed)} demo interview(s) failed clip validation: "
                f"{', '.join(iid for iid, _ in failed)}. Details in {log_path}. "
                f"Demo not recorded; adjust config/prompts and re-run `toolkit clip --demo`.")
        record_demo(project, STEP, fingerprint, units=keys, diag=str(diag_dir))
        print(f"\nDemo review files: open {diag_dir}/index.html")
        print("Review them; adjust config.yaml / prompts/ and re-demo if needed. "
              "Then run `toolkit clip` for the full corpus.")
        reveal(diag_dir / "index.html")
        return clips_df

    clips_out, paras_out = clips_df, paras_df
    if ok:
        out_clips = project.outputs_dir / "clips" / "clips.parquet"
        out_paras = project.outputs_dir / "clips" / "paragraphs_clipped.parquet"
        # A subset or partially-failed run splices its interviews into the existing tables
        # instead of clobbering them.
        if (interviews or failed) and out_clips.exists():
            clips_out = merge_subset(pd.read_parquet(out_clips), clips_df, "interview_id")
            paras_out = merge_subset(pd.read_parquet(out_paras), paras_df, "interview_id")
        write_deliverable(clips_out, out_clips, sort_by="clip_id")
        write_deliverable(paras_out, out_paras, sort_by=["interview_id", "paragraph_idx"])
        print(f"\nWrote {len(clips_out)} clips -> {out_clips}")
        print(f"Wrote {len(paras_out)} paragraph rows -> {out_paras}")
        print(f"Review files: open {diag_dir}/index.html")
        _print_run_stats(clips_df, paras_df)

    if not interviews and not failed:
        record_full(project, STEP, fingerprint, model=model, n_units=len(keys))
    if failed:
        raise ToolkitError(
            f"{len(failed)} interview(s) failed clip validation: "
            f"{', '.join(iid for iid, _ in failed)}. Details in {log_path}. "
            f"Successful interviews were written; re-run `toolkit clip` to retry the failed ones.")
    return clips_out


def _print_run_stats(clips_df: pd.DataFrame, paras_df: pd.DataFrame) -> None:
    per_iv = clips_df.groupby("interview_id").size()
    print(f"\n=== Summary ({clips_df['interview_id'].nunique()} interview(s)) ===")
    print(f"Clips per interview:  mean={per_iv.mean():.1f}  median={per_iv.median():.0f}  "
          f"p10={per_iv.quantile(0.1):.0f}  p90={per_iv.quantile(0.9):.0f}")
    print(f"Paragraphs per clip:  mean={clips_df['n_paragraphs'].mean():.1f}  "
          f"median={clips_df['n_paragraphs'].median():.0f}  max={int(clips_df['n_paragraphs'].max())}")
    print(f"Words per clip:       mean={clips_df['total_words'].mean():.0f}  "
          f"median={clips_df['total_words'].median():.0f}  max={int(clips_df['total_words'].max())}")
    proc_per_iv = paras_df[paras_df["clip_id"] == "procedural"].groupby("interview_id").size()
    if len(proc_per_iv):
        print(f"Procedural paragraphs per interview:  mean={proc_per_iv.mean():.1f}  "
              f"median={proc_per_iv.median():.0f}  max={int(proc_per_iv.max())}")


# --- chunk preview (read-only, no API) -------------------------------------------------------------

def preview_chunks(project: Project) -> None:
    """Print the chunk layout every interview would get under the current config."""
    cfg = load_step_config(project, STEP)
    require(cfg, ["chunk_threshold_tokens", "overlap_paragraphs"], STEP)
    threshold = int(cfg["chunk_threshold_tokens"])
    overlap = int(cfg["overlap_paragraphs"])
    df = load_paragraphs(project)

    rows = []
    for iid, sub in df.groupby("interview_id"):
        chunks = chunk_paragraphs(sub, threshold, overlap)
        est_total = CHUNK_OVERHEAD_BASE + sum(estimate_paragraph_tokens(int(w)) for w in sub["word_count"])
        rows.append({"interview_id": iid, "n_para": len(sub),
                     "est_total_tokens": est_total, "n_chunks": len(chunks), "chunks": chunks})
    rows.sort(key=lambda r: -r["est_total_tokens"])

    print(f"=== Chunk preview (threshold={threshold}, overlap={overlap}) ===")
    print()
    print(f"{'interview_id':<42} {'n_para':>7} {'est_tot':>8}  {'n_ch':>4}  "
          f"layout (shown[d=decision_start, owned=o_s..o_e, ~tokens])")
    print("-" * 140)
    for r in rows:
        layout = "  ".join(
            f"[{c.shown_start}..{c.shown_end}|d={c.decision_start}|own={c.owned_start}..{c.owned_end}|~{c.est_tokens // 1000}k]"
            for c in r["chunks"])
        print(f"{r['interview_id']:<42} {r['n_para']:>7,} {r['est_total_tokens']:>8,}  "
              f"{r['n_chunks']:>4}  {layout}")

    by_n: dict[int, int] = {}
    for r in rows:
        by_n[r["n_chunks"]] = by_n.get(r["n_chunks"], 0) + 1
    print()
    print(f"Chunk-count distribution across {len(rows)} interviews:")
    for n_ch, count in sorted(by_n.items()):
        print(f"  {n_ch} chunk(s): {count} interview(s)")
