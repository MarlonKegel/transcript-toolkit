"""`toolkit cost` — what the LLM steps have actually cost so far, from the per-call caches.

Reads every .toolkit/cache/*.jsonl (or one step's), dedupes to the latest record per cache key,
and groups by (model, reasoning, transport). Each group is priced at the tier it was really
billed at: the batch path stamps `api: "batch"` on the records it writes, so every record
without that field was a synchronous call. The reported total is money spent, not a hypothetical.

`--to-n N` extrapolates the mean per-call cost to N calls (e.g. the full corpus's expected clip
count). That one is a forecast, so it shows both tiers — you have not picked a transport yet.
"""
from __future__ import annotations

from pathlib import Path

from ..core.cache import latest_records
from ..core.cost import USAGE_KEYS, costs, sum_usage
from ..errors import ToolkitError
from ..project import Project

TIER_LABEL = {"standard": "sync ", "batch": "batch"}


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


def run_cost(project: Project, step: str | None = None, to_n: int | None = None) -> None:
    files = _cache_files(project, step)
    if not files:
        print("No LLM calls cached yet — nothing has run.")
        return

    grand = {k: 0 for k in USAGE_KEYS}
    spent = {"standard": 0.0, "batch": 0.0}
    sync_if_batched = 0.0            # what the synchronous spend would have cost on the Batch API
    for path in files:
        records = list(latest_records(path, "cache_key").values())
        if not records:
            continue
        print(f"=== {path.stem} ===")
        groups: dict[tuple[str, str, str], list[dict]] = {}
        for r in records:
            key = (r.get("model", "?"), r.get("reasoning_effort", "?"), _tier(r))
            groups.setdefault(key, []).append(r)
        for (model, reasoning, tier), recs in sorted(groups.items()):
            usage = sum_usage(recs)
            try:
                std, batch = costs(usage, model)
            except ToolkitError as e:
                print(f"  {model}/{reasoning} · {TIER_LABEL[tier]}: {len(recs)} calls — {e}")
                continue
            paid = batch if tier == "batch" else std
            for k in USAGE_KEYS:
                grand[k] += usage[k]
            spent[tier] += paid
            if tier == "standard":
                sync_if_batched += batch
            print(f"  {model}/{reasoning} · {TIER_LABEL[tier]}: {len(recs)} calls · "
                  f"in {usage['input_tokens']:,} (cached {usage['cached_input_tokens']:,}) · "
                  f"reason {usage['reasoning_tokens']:,} · out {usage['output_tokens']:,} · "
                  f"${paid:.4f}")
            if to_n:                 # a forecast: the transport for the next run is still open
                print(f"    -> for {to_n} calls: ${std / len(recs) * to_n:.2f} sync / "
                      f"${batch / len(recs) * to_n:.2f} batch")
    total = spent["standard"] + spent["batch"]
    split = (f"  (sync ${spent['standard']:.4f} + batch ${spent['batch']:.4f})"
             if spent["standard"] and spent["batch"] else "")
    print(f"\nTOTAL so far: ${total:.4f}{split} · "
          f"in {grand['input_tokens']:,} out {grand['output_tokens']:,} tokens")
    if spent["standard"]:
        print(f"The ${spent['standard']:.4f} run synchronously would have been "
              f"${sync_if_batched:.4f} on the Batch API.")
