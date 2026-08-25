"""`toolkit summarize` — one "scope and content" abstract per interview.

One structured-output LLM call per interview unit; a narrator's sessions are pooled by default.
Demo-first: `--demo` summarizes a small seeded sample and writes the review page only; a full run
is demo-gated, confirms cost, writes outputs/summaries/summaries.{parquet,csv} and re-renders
the review page (diags/summarize/*.html). Idempotent + resumable via the per-call cache.
"""
from __future__ import annotations

from concurrent.futures import as_completed
from datetime import datetime, timezone
from threading import Lock

import pandas as pd
from pydantic import create_model

from ..core import cost as costmod
from ..core.batch import fill_cache_via_batch
from ..core.cache import JsonlAppender, cache_key, latest_records
from ..core.config import load_step_config, require
from ..core.console import choose_transport, reveal
from ..core.ids import narrator_key
from ..core.llm import build_schema, call_llm, check_levels, openai_client
from ..core.parallel import worker_pool
from ..core.prompts import load_prompt
from ..core.render import render_interview
from ..core.reviewdoc import document, esc
from ..core.sampling import sample_keys
from ..core.tables import load_paragraphs, merge_subset, write_deliverable
from ..errors import ToolkitError
from ..project import Project
from ..state import check_demo_gate, record_demo, record_full

STEP = "summarize"


# --- assembly -------------------------------------------------------------------------------

def build_units(paragraphs_df: pd.DataFrame, pool_sessions: bool, session_regex: str) -> list[dict]:
    """Group paragraphs into interview units: one per narrator (sessions pooled, in id order)
    or one per session file.

    `untimed` marks a unit whose transcripts were never SYNC'd. A summary is made from the words
    alone, so it is made the same way either way — the flag is what lets `--unsynced` pick those
    out, and what the deliverable records so a reader can tell why such a row has no clips.
    """
    from ..core.tables import untimed_ids

    never_synced = untimed_ids(paragraphs_df)
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
            "untimed": all(sid in never_synced for sid in session_ids),
        })
    return units


def _context(project: Project, pool_sessions_override: bool | None = None):
    cfg = load_step_config(project, STEP)
    require(cfg, ["model", "reasoning", "verbosity", "prompt", "max_workers"], STEP)
    check_levels(cfg["reasoning"], cfg["verbosity"])
    pool = cfg.get("pool_sessions", True) if pool_sessions_override is None else pool_sessions_override
    session_regex = load_step_config(project, "import")["session_regex"]

    instructions = load_prompt(project, cfg["prompt"])
    # `session_regex` is what decides which files are one narrator's sessions, so with pooling on
    # it decides what a summarized unit is — change it and the demo was of different interviews.
    # It is deliberately left out when pooling is off, where it changes nothing.
    shape = f"pool_sessions={pool}" + (f" session_regex={session_regex}" if pool else "")
    fingerprint = cache_key(cfg["model"], cfg["reasoning"], cfg["verbosity"], instructions, shape)
    units = build_units(load_paragraphs(project), pool, session_regex)
    return cfg, instructions, fingerprint, units, pool


# `--unsynced` used to name a second pile with a step record of its own. There is one collection
# now, so it names a subset of it: the transcripts that were never SYNC'd, summarized on their
# own the way `--interview` summarizes chosen ones. One record, because one run of the step over
# everything is what it is.
UNSYNCED = "unsynced"


# --- run ------------------------------------------------------------------------------------

def run_summarize(project: Project, demo: bool = False, interviews: list[str] | None = None,
                  pool_sessions: bool | None = None, yes: bool = False,
                  skip_demo_check: bool = False, batch: bool | None = None,
                  unsynced: bool = False) -> pd.DataFrame:
    if demo and interviews:
        raise ToolkitError("--demo and --interview are mutually exclusive.")
    cfg, instructions, fingerprint, units, pool = _context(project, pool_sessions)
    key = STEP
    what = "transcript(s) that were never SYNC'd" if unsynced else "interview(s)"
    if unsynced:
        # A subset of the one collection, chosen the way `--interview` chooses one.
        units = [u for u in units if u["untimed"]]
        if not units:
            raise ToolkitError(
                f"There are no transcripts in {project.unsynced_dir}/ in the collection. Put "
                f"the ones that were never SYNC'd there and run `toolkit import` again.")
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

    flag = " --unsynced" if unsynced else ""
    use_batch = False
    if not demo:
        check_demo_gate(project, key, fingerprint,
                        demo_command=f"toolkit summarize{flag} --demo", skip=skip_demo_check)
        use_batch = choose_transport(
            f"Summarize {len(selected)} {what} with {model} "
            f"({n_cached} already cached, {n_fresh} fresh call(s)).",
            costmod.estimate_pair(cache, fingerprint, model, n_fresh), yes=yes, batch=batch)

    print(f"Summarizing {len(selected)} {what} · {model}/{reasoning} · "
          f"pooling={'on' if pool else 'off'} · {n_cached} cached / {n_fresh} fresh"
          + (" · Batch API" if use_batch else ""))

    if use_batch:                       # fill the cache first; _run_units then makes no API call
        _batch_fill(project, cfg, instructions, fingerprint, selected, cache, cache_path)
    results = _run_units(project, cfg, instructions, fingerprint, selected, cache, cache_path)

    rows = [{
        "interview_key": u["interview_key"],
        "session_ids": "|".join(u["session_ids"]),
        "n_sessions": u["n_sessions"],
        "n_paragraphs": u["n_paragraphs"],
        "total_words": u["total_words"],
        "summary": results[u["interview_key"]],
        "summary_word_count": len(results[u["interview_key"]].split()),
        # Whether this narrator's transcripts carry times. Everything else works either way, so
        # this is not about what could be made from them — it is what tells a reader of the
        # export why those rows' clips have no start and end.
        "synced": not u["untimed"],
        "model": model,
        "reasoning_effort": reasoning,
    } for u in selected]
    df = pd.DataFrame(rows)

    if demo:
        lead = ("Summaries of transcripts that were never SYNC'd" if unsynced
                else "Interview summaries")
        diag = _write_html(project, df, "demo_summaries.html", title=f"{lead} — DEMO")
        record_demo(project, key, fingerprint, units=keys, diag=str(diag))
        print(f"\nDemo review file: {diag}")
        print(f"Review it; adjust config.yaml / prompts/ and re-demo if needed. "
              f"Then run `toolkit summarize{flag}` for all of them.")
        reveal(diag)
        return df

    out_path = project.outputs_dir / "summaries" / "summaries.parquet"
    existing = pd.read_parquet(out_path) if out_path.exists() else None
    # A run over everything is the whole truth about the collection and replaces the table; a
    # run over a chosen few (`--interview`, `--unsynced`) splices into what is there.
    subset = bool(interviews or unsynced)
    df = merge_subset(existing if subset else None, df, "interview_key")
    write_deliverable(df, out_path, sort_by="interview_key")
    diag = _write_html(project, df.sort_values("interview_key"), "summaries.html",
                       title="Interview summaries")
    if not subset:
        record_full(project, key, fingerprint, model=model, n_units=len(selected))
    print(f"\nWrote {len(df)} summaries -> {out_path}\nReview file: {diag}")
    return df


def _record(u: dict, ck: str, fingerprint: str, summary: str, usage: dict, cfg: dict) -> dict:
    """One cache record — identical shape from either transport, so they stay interchangeable."""
    return {
        "cache_key": ck, "fingerprint": fingerprint,
        "interview_key": u["interview_key"], "session_ids": u["session_ids"],
        "n_sessions": u["n_sessions"], "n_paragraphs": u["n_paragraphs"],
        "total_words": u["total_words"], "summary": summary,
        "model": cfg["model"], "reasoning_effort": cfg["reasoning"], "verbosity": cfg["verbosity"],
        "usage": usage, "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _summarize_schema() -> dict:
    return build_schema(create_model("InterviewSummary", summary=(str, ...)), "interview_summary")


def _batch_fill(project: Project, cfg: dict, instructions: str, fingerprint: str,
                selected: list[dict], cache: dict, cache_path) -> None:
    """Batch transport: one Batch-API job over exactly the uncached interviews."""
    model, reasoning, verbosity = cfg["model"], cfg["reasoning"], cfg["verbosity"]
    pending = []
    for u in selected:
        ck = cache_key(model, reasoning, verbosity, instructions, u["text"])
        if ck not in cache:
            pending.append({"custom_id": u["interview_key"], "user_content": u["text"],
                            "cache_key": ck, "unit": u})

    def make_record(p: dict, parsed: dict, usage: dict) -> dict:
        return _record(p["unit"], p["cache_key"], fingerprint,
                       (parsed.get("summary") or "").strip(), usage, cfg)

    fill_cache_via_batch(
        openai_client(project.root), pending, project.cache_dir / "summarize_batch",
        schema=_summarize_schema(), model=model, reasoning=reasoning, verbosity=verbosity,
        instructions=instructions,
        prompt_cache_key=cache_key(model, reasoning, verbosity, instructions),
        make_record=make_record, cache=cache, appender=JsonlAppender(cache_path),
        poll_interval_s=float(cfg.get("batch_poll_interval_s", 30)),
        max_total_wait_s=float(cfg.get("batch_max_total_wait_s", 86400)),
        unit_noun="interview")


def _run_units(project: Project, cfg: dict, instructions: str, fingerprint: str,
               selected: list[dict], cache: dict, cache_path) -> dict[str, str]:
    model, reasoning, verbosity = cfg["model"], cfg["reasoning"], cfg["verbosity"]
    schema = _summarize_schema()
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
                                 max_total_wait_s=float(cfg.get("max_total_wait_s", 600)))
        summary = (parsed.get("summary") or "").strip()
        record = _record(u, ck, fingerprint, summary, usage, cfg)
        appender.append(record)
        with lock:
            cache[ck] = record
        return u["interview_key"], summary, False

    with worker_pool(int(cfg["max_workers"])) as ex:
        futures = [ex.submit(work, u) for u in selected]
        for i, fut in enumerate(as_completed(futures), start=1):
            key, summary, from_cache = fut.result()
            results[key] = summary
            print(f"  [{i}/{len(selected)}] [{'cached' if from_cache else 'fresh'}] "
                  f"{key}: {len(summary.split())} words")
    return results


# --- review html ----------------------------------------------------------------------------

def _write_html(project: Project, df: pd.DataFrame, filename: str, title: str):
    diag_dir = project.diags_dir / "summarize"
    diag_dir.mkdir(parents=True, exist_ok=True)
    model = df["model"].iloc[0] if len(df) else "?"
    reasoning = df["reasoning_effort"].iloc[0] if len(df) else "?"
    subtitle = (f"<b>{len(df)}</b> interviews · model <code>{esc(model)}</code> · "
                f"reasoning <code>{esc(reasoning)}</code>")
    body: list[str] = []
    for r in df.itertuples():
        body.append('<section class="clip">')
        # Untimed transcripts are said so on the page: they have a summary and will never have a
        # clip, a label or a tag, and somebody reading the summaries has to know which is which.
        untimed = "" if getattr(r, "synced", True) else " · never SYNC'd, so summary only"
        body.append(f"<h2>{esc(r.interview_key)}</h2>")
        body.append(f'<p class="meta">sessions: {esc(r.session_ids)} · {r.n_paragraphs} paragraphs / '
                    f"{r.total_words:,} words · summary {r.summary_word_count} words{untimed}</p>")
        for parag in str(r.summary).split("\n\n"):
            body.append(f"<p>{esc(parag.strip())}</p>")
        body.append("</section>")
    path = diag_dir / filename
    path.write_text(document(title, "\n".join(body), subtitle=subtitle))
    return path


def annotate_summaries(project: Project) -> None:
    out_path = project.outputs_dir / "summaries" / "summaries.parquet"
    if not out_path.exists():
        raise ToolkitError(f"{out_path} not found. Run `toolkit summarize` first.")
    df = pd.read_parquet(out_path).sort_values("interview_key")
    path = _write_html(project, df, "summaries.html", title="Interview summaries")
    print(f"Wrote {path}")
