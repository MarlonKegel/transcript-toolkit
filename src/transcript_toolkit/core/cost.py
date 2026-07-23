"""LLM cost accounting over the per-call caches (ported from shared/lib/cost.py).

Every step's cache record carries the same `usage` shape (input/cached_input/reasoning/output
tokens) plus model/reasoning_effort/ts, so one module prices everything. The price table lives
in defaults/pricing.yaml (package data) — editable without code changes.
"""
from __future__ import annotations

from functools import cache as _memo
from importlib import resources
from typing import Callable

import yaml

from ..errors import ToolkitError

USAGE_KEYS = ("input_tokens", "cached_input_tokens", "reasoning_tokens", "output_tokens")


@_memo
def pricing() -> dict:
    text = (resources.files("transcript_toolkit") / "defaults" / "pricing.yaml").read_text()
    return yaml.safe_load(text)


def cost(inp: int, cached: int, out: int, rates: dict) -> float:
    return ((inp - cached) * rates["input"] + cached * rates["cached"] + out * rates["output"]) / 1e6


def costs(usage: dict, model: str) -> tuple[float, float]:
    """(standard_usd, batch_usd) for a summed-usage dict."""
    table = pricing()
    if model not in table:
        raise ToolkitError(f"No pricing for model {model!r}. Add it to defaults/pricing.yaml "
                           f"(known: {', '.join(sorted(table))}).")
    rates = table[model]
    inp, cached, out = usage["input_tokens"], usage["cached_input_tokens"], usage["output_tokens"]
    return cost(inp, cached, out, rates["standard"]), cost(inp, cached, out, rates["batch"])


def dedupe_latest(records: list[dict], key_fn: Callable[[dict], object]) -> list[dict]:
    """Latest record (by ts) per key — drops orphans left by earlier prompt/config iterations."""
    latest: dict[object, dict] = {}
    for r in records:
        k = key_fn(r)
        prev = latest.get(k)
        if prev is None or r["ts"] > prev["ts"]:
            latest[k] = r
    return list(latest.values())


def sum_usage(records: list[dict]) -> dict:
    tot = {k: 0 for k in USAGE_KEYS}
    for r in records:
        u = r["usage"]
        for k in USAGE_KEYS:
            tot[k] += (u.get(k) or 0)
    return tot


def mean_unit_cost(records: list[dict], model: str) -> tuple[float, float] | None:
    """Mean (standard, batch) USD per record; None if no records."""
    if not records:
        return None
    std, batch = costs(sum_usage(records), model)
    return std / len(records), batch / len(records)


def estimate_pair(cache: dict, fingerprint: str, model: str,
                  n_fresh: int) -> tuple[float, float] | None:
    """Projected (standard_usd, batch_usd) for `n_fresh` fresh calls, extrapolated from the mean
    usage of this fingerprint's cached records. None when there is nothing to extrapolate from
    (no matching cache yet, or nothing fresh to run) — callers then omit the figure rather than
    guess. Shared by every demo-gated step so one run's demo prices its own full run."""
    if n_fresh <= 0:
        return None
    matching = [r for r in cache.values() if r.get("fingerprint") == fingerprint]
    per = mean_unit_cost(matching, model)
    return None if per is None else (per[0] * n_fresh, per[1] * n_fresh)
