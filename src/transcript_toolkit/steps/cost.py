"""`toolkit cost` — what the LLM steps have cost so far, from the per-call caches.

Reads every .toolkit/cache/*.jsonl (or one step's), dedupes to the latest record per cache
key, groups by (model, reasoning), and prints token totals + standard/batch USD. `--to-n N`
extrapolates the mean per-call cost to N calls (e.g. the full corpus's expected clip count).
"""
from __future__ import annotations

from pathlib import Path

from ..core.cache import latest_records
from ..core.cost import USAGE_KEYS, costs, sum_usage
from ..errors import ToolkitError
from ..project import Project


def _cache_files(project: Project, step: str | None) -> list[Path]:
    files = sorted(project.cache_dir.glob("*.jsonl"))
    if step is not None:
        files = [f for f in files if f.stem == step or f.stem.startswith(f"{step}_")]
        if not files:
            raise ToolkitError(f"No cache for step {step!r} under {project.cache_dir}/ "
                               f"(nothing run yet?)")
    return files


def run_cost(project: Project, step: str | None = None, to_n: int | None = None) -> None:
    files = _cache_files(project, step)
    if not files:
        print("No LLM calls cached yet — nothing has run.")
        return

    grand = {k: 0 for k in USAGE_KEYS}
    grand_std = grand_batch = 0.0
    for path in files:
        records = list(latest_records(path, "cache_key").values())
        if not records:
            continue
        print(f"=== {path.stem} ===")
        groups: dict[tuple[str, str], list[dict]] = {}
        for r in records:
            groups.setdefault((r.get("model", "?"), r.get("reasoning_effort", "?")), []).append(r)
        for (model, reasoning), recs in sorted(groups.items()):
            usage = sum_usage(recs)
            try:
                std, batch = costs(usage, model)
            except ToolkitError as e:
                print(f"  {model}/{reasoning}: {len(recs)} calls — {e}")
                continue
            for k in USAGE_KEYS:
                grand[k] += usage[k]
            grand_std += std
            grand_batch += batch
            print(f"  {model}/{reasoning}: {len(recs)} calls · "
                  f"in {usage['input_tokens']:,} (cached {usage['cached_input_tokens']:,}) · "
                  f"reason {usage['reasoning_tokens']:,} · out {usage['output_tokens']:,} · "
                  f"${std:.4f} std / ${batch:.4f} batch")
            if to_n:
                per = std / len(recs)
                print(f"    -> ~${per:.4f}/call · ${per * to_n:.2f} std for {to_n} calls "
                      f"(${batch / len(recs) * to_n:.2f} batch)")
    print(f"\nTOTAL so far: ${grand_std:.4f} std / ${grand_batch:.4f} batch · "
          f"in {grand['input_tokens']:,} out {grand['output_tokens']:,} tokens")
