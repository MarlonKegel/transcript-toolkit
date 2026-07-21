"""`toolkit summarize` — one "scope and content" abstract per interview.

One structured-output LLM call per interview unit; a narrator's sessions are pooled by default.
Demo-first: `--demo` summarizes a small seeded sample and writes the review md only; a full run
is demo-gated, confirms cost, writes outputs/summaries/summaries.{parquet,csv} and re-renders
the review md (diags/summarize/). Idempotent + resumable via the per-call cache.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from threading import Lock

import pandas as pd
from pydantic import create_model

from ..core import cost as costmod
from ..core.cache import JsonlAppender, cache_key, latest_records
from ..core.config import load_step_config, require
from ..core.console import confirm_or_abort
from ..core.ids import narrator_key
from ..core.llm import build_schema, call_llm, check_levels, openai_client
from ..core.render import render_interview
from ..core.sampling import sample_keys
from ..core.tables import load_paragraphs, merge_subset, write_deliverable
from ..errors import ToolkitError
from ..project import Project
from ..state import check_demo_gate, record_demo, record_full

STEP = "summarize"


# --- assembly -------------------------------------------------------------------------------

def load_prompt(project: Project, name: str) -> str:
    path = project.prompts_dir / name
    if not path.exists():
        raise ToolkitError(f"Prompt not found: {path}. Restore the default with "
                           f"`toolkit init --reset-prompt {name}`.")
    return path.read_text().strip()


def build_units(paragraphs_df: pd.DataFrame, pool_sessions: bool, session_regex: str) -> list[dict]:
    """Group paragraphs into interview units: one per narrator (sessions pooled, in id order)
    or one per session file."""
    key_fn = (lambda i: narrator_key(i, session_regex)) if pool_sessions else (lambda i: i)
    keyed: dict[str, list[str]] = {}
    for iid in sorted(paragraphs_df["interview_id"].unique()):
        keyed.setdefault(key_fn(iid), []).append(iid)

    units: list[dict] = []
    for key in sorted(keyed):
        session_ids = sorted(keyed[key])
        frames = [paragraphs_df[paragraphs_df["interview_id"] == sid] for sid in session_ids]
        units.append({
            "interview_key": key,
            "session_ids": session_ids,
            "n_sessions": len(session_ids),
            "n_paragraphs": int(sum(len(f) for f in frames)),
            "total_words": int(sum(int(f["word_count"].sum()) for f in frames)),
            "text": render_interview(frames),
        })
    return units


def _context(project: Project, pool_sessions_override: bool | None):
    cfg = load_step_config(project, STEP)
    require(cfg, ["model", "reasoning", "verbosity", "prompt", "max_workers"], STEP)
    check_levels(cfg["reasoning"], cfg["verbosity"])
    pool = cfg.get("pool_sessions", True) if pool_sessions_override is None else pool_sessions_override
    session_regex = load_step_config(project, "import")["session_regex"]

    instructions = load_prompt(project, cfg["prompt"])
    fingerprint = cache_key(cfg["model"], cfg["reasoning"], cfg["verbosity"], instructions,
                            f"pool_sessions={pool}")
    units = build_units(load_paragraphs(project), pool, session_regex)
    return cfg, instructions, fingerprint, units, pool


# --- run ------------------------------------------------------------------------------------

def run_summarize(project: Project, demo: bool = False, interviews: list[str] | None = None,
                  pool_sessions: bool | None = None, yes: bool = False,
                  skip_demo_check: bool = False) -> pd.DataFrame:
    if demo and interviews:
        raise ToolkitError("--demo and --interview are mutually exclusive.")
    cfg, instructions, fingerprint, units, pool = _context(project, pool_sessions)
    by_key = {u["interview_key"]: u for u in units}

    if demo:
        keys = sample_keys(list(by_key), int(cfg.get("demo_n", 2)), int(cfg.get("demo_seed", 0)))
    elif interviews:
        unknown = [k for k in interviews if k not in by_key]
        if unknown:
            raise ToolkitError(f"Unknown interview key(s): {', '.join(unknown)}. "
                               f"Available: {', '.join(sorted(by_key))}")
        keys = sorted(interviews)
    else:
        keys = sorted(by_key)
    selected = [by_key[k] for k in keys]

    cache_path = project.cache_dir / "summarize.jsonl"
    cache = latest_records(cache_path, "cache_key")
    model, reasoning, verbosity = cfg["model"], cfg["reasoning"], cfg["verbosity"]

    def unit_ck(u: dict) -> str:
        return cache_key(model, reasoning, verbosity, instructions, u["text"])

    n_cached = sum(1 for u in selected if unit_ck(u) in cache)
    n_fresh = len(selected) - n_cached

    if not demo:
        check_demo_gate(project, STEP, fingerprint,
                        demo_command="toolkit summarize --demo", skip=skip_demo_check)
        estimate = _estimate(cache, fingerprint, model, n_fresh)
        confirm_or_abort(
            f"Summarize {len(selected)} interview(s) with {model} "
            f"({n_cached} already cached, {n_fresh} fresh API calls{estimate})?", yes)

    print(f"Summarizing {len(selected)} interview(s) · {model}/{reasoning} · "
          f"pooling={'on' if pool else 'off'} · {n_cached} cached / {n_fresh} fresh")

    results = _run_units(project, cfg, instructions, fingerprint, selected, cache, cache_path)

    rows = [{
        "interview_key": u["interview_key"],
        "session_ids": "|".join(u["session_ids"]),
        "n_sessions": u["n_sessions"],
        "n_paragraphs": u["n_paragraphs"],
        "total_words": u["total_words"],
        "summary": results[u["interview_key"]],
        "summary_word_count": len(results[u["interview_key"]].split()),
        "model": model,
        "reasoning_effort": reasoning,
    } for u in selected]
    df = pd.DataFrame(rows)

    if demo:
        diag = _write_md(project, df, "demo_summaries.md",
                         title="Interview summaries — DEMO")
        record_demo(project, STEP, fingerprint, units=keys, diag=str(diag))
        print(f"\nDemo review file: {diag}")
        print("Review it; adjust config.yaml / prompts/ and re-demo if needed. "
              "Then run `toolkit summarize` for the full corpus.")
        return df

    out_path = project.outputs_dir / "summaries" / "summaries.parquet"
    if interviews and out_path.exists():
        df = merge_subset(pd.read_parquet(out_path), df, "interview_key")
    write_deliverable(df, out_path, sort_by="interview_key")
    diag = _write_md(project, df.sort_values("interview_key"), "summaries.md",
                     title="Interview summaries")
    if not interviews:
        record_full(project, STEP, fingerprint, model=model, n_units=len(selected))
    print(f"\nWrote {len(df)} summaries -> {out_path}\nReview file: {diag}")
    return df


def _estimate(cache: dict, fingerprint: str, model: str, n_fresh: int) -> str:
    matching = [r for r in cache.values() if r.get("fingerprint") == fingerprint]
    per = costmod.mean_unit_cost(matching, model)
    if per is None or n_fresh == 0:
        return ""
    return f", ~${per[0] * n_fresh:.2f} est."


def _run_units(project: Project, cfg: dict, instructions: str, fingerprint: str,
               selected: list[dict], cache: dict, cache_path) -> dict[str, str]:
    model, reasoning, verbosity = cfg["model"], cfg["reasoning"], cfg["verbosity"]
    schema = build_schema(create_model("InterviewSummary", summary=(str, ...)), "interview_summary")
    prompt_cache_key_str = cache_key(model, reasoning, verbosity, instructions)
    client = None
    if any(cache_key(model, reasoning, verbosity, instructions, u["text"]) not in cache
           for u in selected):
        client = openai_client(project.root)
    appender = JsonlAppender(cache_path)
    lock = Lock()
    results: dict[str, str] = {}

    def work(u: dict) -> tuple[str, str, bool]:
        ck = cache_key(model, reasoning, verbosity, instructions, u["text"])
        with lock:
            hit = cache.get(ck)
        if hit is not None:
            return u["interview_key"], hit["summary"], True
        parsed, usage = call_llm(client, model, reasoning, verbosity, schema,
                                 instructions, u["text"], prompt_cache_key_str,
                                 poll_interval_s=float(cfg.get("poll_interval_s", 4)),
                                 max_total_wait_s=float(cfg.get("max_total_wait_s", 1800)))
        summary = (parsed.get("summary") or "").strip()
        record = {
            "cache_key": ck, "fingerprint": fingerprint,
            "interview_key": u["interview_key"], "session_ids": u["session_ids"],
            "n_sessions": u["n_sessions"], "n_paragraphs": u["n_paragraphs"],
            "total_words": u["total_words"], "summary": summary,
            "model": model, "reasoning_effort": reasoning, "verbosity": verbosity,
            "usage": usage, "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        appender.append(record)
        with lock:
            cache[ck] = record
        return u["interview_key"], summary, False

    with ThreadPoolExecutor(max_workers=int(cfg["max_workers"])) as ex:
        futures = [ex.submit(work, u) for u in selected]
        for i, fut in enumerate(as_completed(futures), start=1):
            key, summary, from_cache = fut.result()
            results[key] = summary
            print(f"  [{i}/{len(selected)}] [{'cached' if from_cache else 'fresh'}] "
                  f"{key}: {len(summary.split())} words")
    return results


# --- review md ------------------------------------------------------------------------------

def _write_md(project: Project, df: pd.DataFrame, filename: str, title: str):
    diag_dir = project.diags_dir / "summarize"
    diag_dir.mkdir(parents=True, exist_ok=True)
    model = df["model"].iloc[0] if len(df) else "?"
    reasoning = df["reasoning_effort"].iloc[0] if len(df) else "?"
    lines = [f"# {title}", "",
             f"{len(df)} interviews · model `{model}` · reasoning `{reasoning}`", ""]
    for r in df.itertuples():
        lines.append(f"## {r.interview_key}")
        lines.append("")
        lines.append(f"*sessions: {r.session_ids} · {r.n_paragraphs} paragraphs / "
                     f"{r.total_words:,} words · summary {r.summary_word_count} words*")
        lines.append("")
        lines.append(r.summary)
        lines.append("")
    path = diag_dir / filename
    path.write_text("\n".join(lines))
    return path


def annotate_summaries(project: Project) -> None:
    out_path = project.outputs_dir / "summaries" / "summaries.parquet"
    if not out_path.exists():
        raise ToolkitError(f"{out_path} not found. Run `toolkit summarize` first.")
    df = pd.read_parquet(out_path).sort_values("interview_key")
    path = _write_md(project, df, "summaries.md", title="Interview summaries")
    print(f"Wrote {path}")
