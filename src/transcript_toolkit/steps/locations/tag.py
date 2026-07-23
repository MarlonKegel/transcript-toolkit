"""`toolkit locations tag` — tag each clip to the countries and regions it is substantively about.

One structured-output LLM call per clip. The model returns two lists of {place, label} objects:
`countries` = {place, country} (the place as mentioned + the free-text country it aggregates to)
and `regions` = {place, region} (the place + its acceptable region — a strict enum built from the
workspace's locations/regions.yaml, which is also injected into the prompt so prompt and schema
never drift). A place gets a country XOR a region; either list may be empty. Demo runs add a
per-place justification (prompts/justify_locations.md) for review.

Demo-first: `--demo` tags a seeded spread-across-interviews sample and writes diags/locations/demo.html
only; a full run is demo-gated, confirms cost, and writes outputs/locations/clip_locations{,_long}.
`--batch` fills the cache for the missing clips via the Batch API (50%-off), then builds the same
deliverables from cache. Idempotent + resumable via .toolkit/cache/locations.jsonl.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from threading import Lock
from typing import Literal

import pandas as pd
import yaml
from pydantic import create_model

from ...core import cost as costmod
from ...core.batch import run_batch
from ...core.cache import JsonlAppender, cache_key, latest_records
from ...core.config import load_step_config, require
from ...core.console import confirm_or_abort, reveal
from ...core.llm import build_schema, call_llm, check_levels, openai_client
from ...core.render import render_clip_plain
from ...core.sampling import sample_clips_spread
from ...core.tables import (load_clips, load_paragraphs, merge_subset, paragraphs_by_interview,
                            write_deliverable)
from ...errors import ToolkitError
from ...project import Project
from ...state import check_demo_gate, record_demo, record_full
from .annotate import write_review_html

STEP = "locations"


# --- assembly -------------------------------------------------------------------------------

def load_prompt(project: Project, name: str) -> str:
    path = project.prompts_dir / name
    if not path.exists():
        raise ToolkitError(f"Prompt not found: {path}. Restore the default with "
                           f"`toolkit init --reset-prompt {name}`.")
    return path.read_text().strip()


def load_regions(project: Project, cfg: dict) -> list[str]:
    """The canonical region vocabulary (workspace locations/regions.yaml) — the single source of
    truth: injected into the prompt AND used to build the schema enum."""
    path = project.root / cfg["regions_file"]
    if not path.exists():
        raise ToolkitError(f"Regions file not found: {path} (advanced key regions_file).")
    regions = yaml.safe_load(path.read_text())
    if not isinstance(regions, list) or not all(isinstance(r, str) for r in regions):
        raise ToolkitError(f"{path} must be a YAML list of region names.")
    if not regions:
        raise ToolkitError(f"{path} is empty; the acceptable-region vocabulary is required.")
    return regions


def build_instructions(prompt_text: str, regions: list[str], justify_addendum: str = "") -> str:
    """Assemble the stable, cacheable instructions block: the task prompt, then the canonical
    region list (injected here so the prompt file and the schema enum share one source), then the
    optional justification addendum. BYTE-STABILITY: this text feeds cache keys and the demo
    fingerprint — keep it byte-identical to the working repo's build_instructions."""
    if not regions:
        raise ToolkitError("The region vocabulary is empty; cannot build instructions.")
    region_block = "## Acceptable regions\n\n" + "\n".join(f"- {r}" for r in regions)
    parts = [prompt_text, region_block]
    if justify_addendum:
        parts.append(justify_addendum)
    return "\n\n".join(parts) + "\n"


def build_location_model(regions: list[str], justify: bool = False):
    """Pydantic model for the structured response:

        { "countries": [ {place, country[, justification]}, ... ],   # place <= country level -> its country
          "regions":   [ {place, region [, justification]}, ... ] }  # supranational place -> acceptable region

    Region labels are a strict enum from `regions`; country labels are free text (historical
    states allowed). When `justify` is on, each entry carries a one-sentence justification."""
    if not regions:
        raise ToolkitError("The region vocabulary is empty; cannot build the region enum.")
    region_enum = Literal[tuple(regions)]
    cfields = {"place": (str, ...), "country": (str, ...)}
    rfields = {"place": (str, ...), "region": (region_enum, ...)}
    if justify:
        cfields["justification"] = (str, ...)
        rfields["justification"] = (str, ...)
    country_place = create_model("CountryPlace", **cfields)
    region_place = create_model("RegionPlace", **rfields)
    return create_model("ClipLocations",
                        countries=(list[country_place], ...), regions=(list[region_place], ...))


def clean_entries(entries, label_key: str) -> list[dict]:
    """De-dup a list of {place, <label_key>[, justification]} objects (case-insensitive on place +
    label), dropping any entry missing its aggregation label. Order-preserving; keeps the per-place
    justification when present (justify runs)."""
    out, seen = [], set()
    for e in entries or []:
        place = (e.get("place") or "").strip()
        label = (e.get(label_key) or "").strip()
        if not label:
            continue
        k = (place.casefold(), label.casefold())
        if k not in seen:
            seen.add(k)
            row = {"place": place, label_key: label}
            if "justification" in e:
                row["justification"] = (e.get("justification") or "").strip()
            out.append(row)
    return out


def labels(entries: list[dict], label_key: str) -> list[str]:
    """Unique aggregation labels (order-preserving) across cleaned entries."""
    out, seen = [], set()
    for e in entries:
        v = e[label_key]
        if v.casefold() not in seen:
            seen.add(v.casefold())
            out.append(v)
    return out


def _context(project: Project, justify: bool):
    cfg = load_step_config(project, STEP)
    require(cfg, ["model", "reasoning", "verbosity", "prompt", "justify_prompt", "max_workers",
                  "regions_file", "demo_n_clips", "demo_seed"], STEP)
    check_levels(cfg["reasoning"], cfg["verbosity"])
    regions = load_regions(project, cfg)
    prompt_text = load_prompt(project, cfg["prompt"])
    addendum = load_prompt(project, cfg["justify_prompt"]) if justify else ""
    instructions = build_instructions(prompt_text, regions, addendum)
    # The fingerprint deliberately EXCLUDES the justify addendum: justifications change the review
    # payload, not the tagging, so a justify-on demo (the default) approves a justify-off full run.
    base_instructions = build_instructions(prompt_text, regions, "")
    fingerprint = cache_key(cfg["model"], cfg["reasoning"], cfg["verbosity"], base_instructions)
    return cfg, regions, instructions, fingerprint


# --- run ------------------------------------------------------------------------------------

def run_locations_tag(project: Project, demo: bool = False, sample_n: int | None = None,
                      seed: int | None = None, interviews: list[str] | None = None,
                      justify: bool | None = None, batch: bool = False, yes: bool = False,
                      skip_demo_check: bool = False) -> pd.DataFrame:
    if demo and (sample_n or interviews):
        raise ToolkitError("--demo cannot be combined with --sample or --interview.")
    justify = demo if justify is None else justify        # demo default: justifications on
    cfg, regions, instructions, fingerprint = _context(project, justify)
    model, reasoning, verbosity = cfg["model"], cfg["reasoning"], cfg["verbosity"]
    schema = build_schema(build_location_model(regions, justify=justify), "clip_locations")
    prompt_cache_key_str = cache_key(model, reasoning, verbosity, instructions)  # stable across clips

    clips_df = load_clips(project)
    para_by_interview = paragraphs_by_interview(load_paragraphs(project))

    if demo:
        picked = sample_clips_spread(clips_df, int(cfg["demo_n_clips"]), int(cfg["demo_seed"]))
        clips_sel = clips_df[clips_df["clip_id"].isin(picked)]
    elif interviews:
        unknown = sorted(set(interviews) - set(clips_df["interview_id"]))
        if unknown:
            raise ToolkitError(f"Unknown interview id(s): {', '.join(unknown)}. "
                               f"Available: {', '.join(sorted(clips_df['interview_id'].unique()))}")
        clips_sel = clips_df[clips_df["interview_id"].isin(interviews)]
    elif sample_n:
        picked = sample_clips_spread(clips_df, int(sample_n), int(seed or 0))
        clips_sel = clips_df[clips_df["clip_id"].isin(picked)]
    else:
        clips_sel = clips_df
    clips_sel = clips_sel.sort_values(["interview_id", "start_paragraph_idx"]).reset_index(drop=True)
    subset = bool(interviews or sample_n)

    # units: clip + rendered user content + its cache key (the key includes the ACTUAL
    # instructions, so justify-on and justify-off taggings cache separately)
    units = [{
        "clip_id": r.clip_id, "interview_id": r.interview_id,
        "user_content": render_clip_plain(r.clip_id, int(r.start_paragraph_idx),
                                          int(r.end_paragraph_idx), para_by_interview[r.interview_id]),
    } for r in clips_sel.itertuples()]
    for u in units:
        u["cache_key"] = cache_key(model, reasoning, verbosity, instructions, u["user_content"])

    cache_path = project.cache_dir / "locations.jsonl"
    cache = latest_records(cache_path, "cache_key")
    n_cached = sum(1 for u in units if u["cache_key"] in cache)
    n_fresh = len(units) - n_cached

    if not demo:
        check_demo_gate(project, STEP, fingerprint,
                        demo_command="toolkit locations tag --demo", skip=skip_demo_check)
        estimate = _estimate(cache, fingerprint, model, n_fresh, batch)
        confirm_or_abort(
            f"Tag {len(units)} clip(s) with {model}{' via the Batch API' if batch else ''} "
            f"({n_cached} already cached, {n_fresh} fresh API calls{estimate})?", yes)

    print(f"Tagging {len(units)} clip(s) · {model}/{reasoning} · justify={'on' if justify else 'off'} · "
          f"{len(regions)} regions · {n_cached} cached / {n_fresh} fresh"
          + (" · batch transport" if batch else ""))

    if batch:
        _run_batch_units(project, cfg, instructions, fingerprint, schema,
                         prompt_cache_key_str, units, cache, cache_path)
    else:
        _run_units(project, cfg, instructions, fingerprint, schema,
                   prompt_cache_key_str, units, cache, cache_path)

    # --- deliverable frames: per-clip rollup (wide) + one row per extracted place (long) ------
    wide_rows, long_rows = [], []
    for u in units:
        rec = cache[u["cache_key"]]
        cents = clean_entries(rec["countries"], "country")
        rents = clean_entries(rec["regions"], "region")
        cnames, rnames = labels(cents, "country"), labels(rents, "region")
        wide_rows.append({"clip_id": u["clip_id"], "countries": "|".join(cnames),
                          "regions": "|".join(rnames), "n_countries": len(cnames),
                          "n_regions": len(rnames), "has_place": bool(cents or rents)})
        for kind, key, ents in (("country", "country", cents), ("region", "region", rents)):
            for e in ents:
                long_rows.append({"interview_id": u["interview_id"], "clip_id": u["clip_id"],
                                  "place": e["place"], "label": e[key], "kind": kind,
                                  "justification": e.get("justification", "")})
    meta_cols = ["interview_id", "clip_id", "start_paragraph_idx", "end_paragraph_idx",
                 "n_paragraphs", "total_words", "start_ts", "end_ts"]
    wide = clips_sel[meta_cols].merge(pd.DataFrame(wide_rows), on="clip_id")
    wide["model"] = model
    wide["reasoning_effort"] = reasoning
    long = pd.DataFrame(long_rows, columns=["interview_id", "clip_id", "place", "label",
                                            "kind", "justification"])

    if demo:
        diag = write_review_html(project, wide, long, para_by_interview, "demo.html",
                                 title="Clip locations — DEMO")
        record_demo(project, STEP, fingerprint, units=sorted(wide["clip_id"]), diag=str(diag))
        print(f"\nDemo review file: {diag}")
        print("Review it; adjust config.yaml / prompts/ / locations/ and re-demo if needed. "
              "Then run `toolkit locations tag` for the full corpus.")
        reveal(diag)
        return wide

    out_dir = project.outputs_dir / "locations"
    wide_path = out_dir / "clip_locations.parquet"
    long_path = out_dir / "clip_locations_long.parquet"
    if subset and wide_path.exists():                    # merge at clip granularity, never clobber
        wide = merge_subset(pd.read_parquet(wide_path), wide, "clip_id")
    if subset and long_path.exists():
        long = merge_subset(pd.read_parquet(long_path), long, "clip_id")
    write_deliverable(wide, wide_path, sort_by=["interview_id", "start_paragraph_idx"])
    write_deliverable(long, long_path, sort_by=["interview_id", "clip_id"])
    if not subset:
        record_full(project, STEP, fingerprint, model=model, n_units=len(units))
    n_place = int(wide["has_place"].sum())
    print(f"\nWrote {len(wide)} clip taggings -> {wide_path}")
    print(f"      {len(long)} place rows -> {long_path}")
    print(f"Clips with >=1 place: {n_place}/{len(wide)} ({100 * n_place / max(len(wide), 1):.0f}%). "
          f"Next: `toolkit locations map`.")
    return wide


def _estimate(cache: dict, fingerprint: str, model: str, n_fresh: int, batch: bool) -> str:
    matching = [r for r in cache.values() if r.get("fingerprint") == fingerprint]
    per = costmod.mean_unit_cost(matching, model)
    if per is None or n_fresh == 0:
        return ""
    return f", ~${per[1 if batch else 0] * n_fresh:.2f} est."


def _record(u: dict, fingerprint: str, parsed: dict, usage: dict, cfg: dict) -> dict:
    return {
        "cache_key": u["cache_key"], "fingerprint": fingerprint,
        "clip_id": u["clip_id"], "interview_id": u["interview_id"],
        "countries": clean_entries(parsed.get("countries"), "country"),
        "regions": clean_entries(parsed.get("regions"), "region"),
        "model": cfg["model"], "reasoning_effort": cfg["reasoning"], "verbosity": cfg["verbosity"],
        "usage": usage, "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _run_units(project: Project, cfg: dict, instructions: str, fingerprint: str, schema: dict,
               prompt_cache_key_str: str, units: list[dict], cache: dict, cache_path) -> None:
    """Standard transport: one background-mode call per cache-missing clip, threaded."""
    model, reasoning, verbosity = cfg["model"], cfg["reasoning"], cfg["verbosity"]
    client = openai_client(project.root) if any(u["cache_key"] not in cache for u in units) else None
    appender = JsonlAppender(cache_path)
    lock = Lock()

    def work(u: dict) -> tuple[str, dict, bool]:
        with lock:
            hit = cache.get(u["cache_key"])
        if hit is not None:
            return u["clip_id"], hit, True
        parsed, usage = call_llm(client, model, reasoning, verbosity, schema,
                                 instructions, u["user_content"], prompt_cache_key_str,
                                 poll_interval_s=float(cfg.get("poll_interval_s", 4)),
                                 max_total_wait_s=float(cfg.get("max_total_wait_s", 1800)))
        record = _record(u, fingerprint, parsed, usage, cfg)
        appender.append(record)
        with lock:
            cache[u["cache_key"]] = record
        return u["clip_id"], record, False

    with ThreadPoolExecutor(max_workers=int(cfg["max_workers"])) as ex:
        futures = [ex.submit(work, u) for u in units]
        for i, fut in enumerate(as_completed(futures), start=1):
            cid, rec, from_cache = fut.result()
            print(f"  [{i}/{len(units)}] [{'cached' if from_cache else 'fresh'}] {cid}: "
                  f"{len(rec['countries'])} countr(y/ies), {len(rec['regions'])} region(s)")


def _run_batch_units(project: Project, cfg: dict, instructions: str, fingerprint: str, schema: dict,
                     prompt_cache_key_str: str, units: list[dict], cache: dict, cache_path) -> None:
    """Batch transport: one Batch-API job over exactly the cache-missing clips; identical cache
    records (marked api: batch), so the two transports are interchangeable per clip."""
    model, reasoning, verbosity = cfg["model"], cfg["reasoning"], cfg["verbosity"]
    pending = [u for u in units if u["cache_key"] not in cache]
    if not pending:
        print("  nothing pending; building deliverables from cache.")
        return
    batch_units = [{"custom_id": u["clip_id"], "instructions": instructions,
                    "user_content": u["user_content"], "schema": schema, "model": model,
                    "reasoning": reasoning, "verbosity": verbosity,
                    "prompt_cache_key": prompt_cache_key_str} for u in pending]
    results, failures = run_batch(openai_client(project.root), batch_units,
                                  project.cache_dir / "locations_batch",
                                  poll_interval_s=float(cfg.get("poll_interval_s", 4)),
                                  max_total_wait_s=float(cfg.get("max_total_wait_s", 1800)))
    appender = JsonlAppender(cache_path)
    by_id = {u["clip_id"]: u for u in pending}
    for cid, (parsed, usage) in results.items():
        u = by_id[cid]
        record = {**_record(u, fingerprint, parsed, usage, cfg), "api": "batch"}
        appender.append(record)
        cache[u["cache_key"]] = record
    print(f"  batch: cached {len(results)} of {len(pending)} pending clips")
    uncached = [u["clip_id"] for u in pending if u["cache_key"] not in cache]
    if failures or uncached:                             # failed requests stay uncached; re-run
        raise ToolkitError(                              # batches exactly the missing clips
            f"Batch run left {len(uncached)} of {len(pending)} pending clip(s) uncached "
            f"({len(failures)} failed request(s), e.g. {failures[:3] or uncached[:3]}). "
            f"Successful results are cached; re-run the same command to batch just the rest.")


# --- preview --------------------------------------------------------------------------------

def preview_call(project: Project, clip_id: str | None = None) -> None:
    """Print exactly what one tagging call sends (instructions + a clip's user content); no API
    call. Full-run instructions are shown — demos append the justify addendum on top."""
    cfg, regions, instructions, fingerprint = _context(project, justify=False)
    clips_df = load_clips(project).sort_values(["interview_id", "start_paragraph_idx"])
    if clip_id is None:
        row = clips_df.iloc[0]
    else:
        match = clips_df[clips_df["clip_id"] == clip_id]
        if match.empty:
            raise ToolkitError(f"Unknown clip_id {clip_id!r}.")
        row = match.iloc[0]
    para_by_interview = paragraphs_by_interview(load_paragraphs(project))
    user_content = render_clip_plain(row["clip_id"], int(row["start_paragraph_idx"]),
                                     int(row["end_paragraph_idx"]),
                                     para_by_interview[row["interview_id"]])
    print("=== instructions (stable, cached prefix; demos append the justify addendum) ===\n")
    print(instructions)
    print(f"=== user content — clip {row['clip_id']} ===\n")
    print(user_content)
    print(f"model {cfg['model']} · reasoning {cfg['reasoning']} · verbosity {cfg['verbosity']} · "
          f"{len(regions)} regions · fingerprint {fingerprint}")
