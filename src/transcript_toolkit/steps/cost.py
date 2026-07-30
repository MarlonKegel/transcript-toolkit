"""`toolkit cost` — the project's cost report: what has actually been billed, per step and total.

Every LLM call a step makes is appended to that step's cache under `.toolkit/cache/*.jsonl`, with
the tokens it used and the model it used them on, and a call that hits the cache is never sent
again — so one line in a cache file is one call that was paid for. Adding them all up is money
spent, not an estimate: it includes demos, and everything left behind by a prompt that has since
been rewritten.

Each call is priced at the tier it was really billed at. The batch path stamps `api: "batch"` on
the records it writes, so a record without that field was a synchronous call.

`--to-n N` is the one forecast here: it extrapolates the mean cost per call to N calls (e.g. the
clip count of a full corpus). It shows both tiers, because that transport has not been chosen yet.

`spend_report` returns the same figures as data, so the app's cost report and this printed one
are one calculation with two renderings and cannot disagree.
"""
from __future__ import annotations

from pathlib import Path

from ..core.cache import iter_jsonl
from ..core.cost import USAGE_KEYS, costs, pricing_note, sum_usage
from ..errors import ToolkitError
from ..project import Project

TIER_LABEL = {"standard": "sync ", "batch": "batch"}


def calls(n: int) -> str:
    return f"{n:,} call{'s' if n != 1 else ''}"


def _tier(record: dict) -> str:
    """Which price list this call was billed at. Only `core.batch` stamps api=batch; a record
    without the field came from the synchronous transport."""
    return "batch" if record.get("api") == "batch" else "standard"


def _cache_files(project: Project, step: str | None) -> list[Path]:
    files = sorted(project.cache_dir.glob("*.jsonl"))
    if step is not None:
        files = [f for f in files if f.stem == step or f.stem.startswith(f"{step}_")]
        if not files:
            raise ToolkitError(f"No cache for step {step!r} under {project.cache_dir}/ "
                               f"(nothing run yet?)")
    return files


def step_key_of(stem: str) -> str:
    """The step a cache file belongs to, named the way state.json names it — `topics_main.jsonl`
    holds the topic list 'main', which is the step `topics:main`."""
    return f"topics:{stem[len('topics_'):]}" if stem.startswith("topics_") else stem


def spend_report(project: Project, step: str | None = None) -> dict:
    """What has been spent, as data: per step, per model/effort/transport, and in total.

    Every record counts. The latest-record-per-key rule the steps use to read their caches is
    deliberately not applied here — a superseded record is still a call that was paid for.
    """
    report = {"steps": [], "total_usd": 0.0, "calls": 0,
              "by_tier": {"standard": 0.0, "batch": 0.0},
              "usage": {k: 0 for k in USAGE_KEYS},
              "sync_if_batched": 0.0, "unpriced": [], "note": pricing_note()}

    for path in _cache_files(project, step):
        records = list(iter_jsonl(path))
        if not records:
            continue
        groups: dict[tuple[str, str, str], list[dict]] = {}
        for r in records:
            groups.setdefault((r.get("model", "?"), r.get("reasoning_effort", "?"), _tier(r)),
                              []).append(r)

        entry = {"key": step_key_of(path.stem), "cache": path.name, "calls": 0, "usd": 0.0,
                 "usage": {k: 0 for k in USAGE_KEYS}, "groups": [], "unpriced": []}
        for (model, reasoning, tier), recs in sorted(groups.items()):
            usage = sum_usage(recs)
            try:
                std, batch = costs(usage, model)
            except ToolkitError as e:
                entry["unpriced"].append({"model": model, "calls": len(recs), "why": str(e)})
                report["unpriced"].append({"step": entry["key"], "model": model,
                                           "calls": len(recs)})
                continue
            paid = batch if tier == "batch" else std
            entry["groups"].append({"model": model, "reasoning": reasoning, "tier": tier,
                                    "calls": len(recs), "usage": usage, "usd": paid,
                                    "sync_usd": std, "batch_usd": batch})
            entry["calls"] += len(recs)
            entry["usd"] += paid
            for k in USAGE_KEYS:
                entry["usage"][k] += usage[k]
                report["usage"][k] += usage[k]
            report["by_tier"][tier] += paid
            report["total_usd"] += paid
            report["calls"] += len(recs)
            if tier == "standard":
                report["sync_if_batched"] += batch
        report["steps"].append(entry)
    return report


def spent_on(report: dict, step_key: str) -> dict | None:
    """One step's line out of a report, or None if it has never made a call."""
    return next((e for e in report["steps"] if e["key"] == step_key), None)


def run_cost(project: Project, step: str | None = None, to_n: int | None = None) -> None:
    report = spend_report(project, step)
    if not report["steps"]:
        print("No LLM calls cached yet — nothing has run, so nothing has been billed.")
        return

    print("=== Project cost report ===")
    print("Everything billed in this project so far, demos included.\n")
    for entry in report["steps"]:
        print(f"{entry['key']}: ${entry['usd']:.4f} · {calls(entry['calls'])}")
        for g in entry["groups"]:
            usage = g["usage"]
            print(f"  {g['model']}/{g['reasoning']} · {TIER_LABEL[g['tier']]}: "
                  f"{calls(g['calls'])} · "
                  f"in {usage['input_tokens']:,} (cached {usage['cached_input_tokens']:,}) · "
                  f"reason {usage['reasoning_tokens']:,} · out {usage['output_tokens']:,} · "
                  f"${g['usd']:.4f}")
            if to_n:             # a forecast: the transport for the next run is still open
                print(f"    -> for {to_n} calls: ${g['sync_usd'] / g['calls'] * to_n:.2f} sync / "
                      f"${g['batch_usd'] / g['calls'] * to_n:.2f} batch")
        for missing in entry["unpriced"]:
            print(f"  {missing['model']}: {calls(missing['calls'])} — {missing['why']}")

    spent, usage = report["by_tier"], report["usage"]
    split = (f"  (sync ${spent['standard']:.4f} + batch ${spent['batch']:.4f})"
             if spent["standard"] and spent["batch"] else "")
    print(f"\nTOTAL so far: ${report['total_usd']:.4f}{split} · {calls(report['calls'])} · "
          f"in {usage['input_tokens']:,} out {usage['output_tokens']:,} tokens")
    if spent["standard"]:
        print(f"The ${spent['standard']:.4f} run synchronously would have been "
              f"${report['sync_if_batched']:.4f} on the Batch API.")
    if report["note"]:
        print(f"\n{report['note']}")
