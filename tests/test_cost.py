"""`toolkit cost` reports money actually spent: each group is priced at the tier it was really
billed at, decided by the `api` field the batch path stamps on its records."""
import json

import pytest

from transcript_toolkit.project import init_project
from transcript_toolkit.steps.cost import run_cost

# gpt-5.4-mini: standard {in 0.75, cached 0.075, out 4.50} / batch = exactly half.
# 1,000,000 uncached input + 1,000,000 output -> $0.75 + $4.50 = $5.25 standard, $2.625 batch.
USAGE = {"input_tokens": 1_000_000, "output_tokens": 1_000_000,
         "reasoning_tokens": 0, "cached_input_tokens": 0}
MODEL = "gpt-5.4-mini"


@pytest.fixture
def project(tmp_path):
    return init_project(str(tmp_path / "ws"))


def write_cache(project, name: str, records: list[dict]) -> None:
    path = project.cache_dir / f"{name}.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records))


def record(key: str, api: str | None = None) -> dict:
    r = {"cache_key": key, "model": MODEL, "reasoning_effort": "medium", "usage": USAGE}
    if api:
        r["api"] = api
    return r


def test_synchronous_records_priced_at_standard(project, capsys):
    write_cache(project, "topics_main", [record("a")])
    run_cost(project)
    out = capsys.readouterr().out
    assert "sync" in out and "$5.2500" in out
    assert "TOTAL so far: $5.2500" in out
    assert "$2.6250 on the Batch API" in out          # what it would have cost batched


def test_batch_records_priced_at_batch(project, capsys):
    write_cache(project, "topics_main", [record("a", api="batch")])
    run_cost(project)
    out = capsys.readouterr().out
    assert "batch" in out and "$2.6250" in out
    assert "TOTAL so far: $2.6250" in out
    assert "would have been" not in out               # nothing ran synchronously


def test_mixed_transports_split_and_sum(project, capsys):
    write_cache(project, "topics_main", [record("a"), record("b", api="batch")])
    run_cost(project)
    out = capsys.readouterr().out
    # one line per transport, and the total is the real sum (5.25 + 2.625), not a both-ways guess
    assert "TOTAL so far: $7.8750" in out
    assert "(sync $5.2500 + batch $2.6250)" in out


def test_total_spans_steps(project, capsys):
    write_cache(project, "label", [record("a")])
    write_cache(project, "topics_main", [record("b", api="batch")])
    run_cost(project)
    out = capsys.readouterr().out
    assert "=== label ===" in out and "=== topics_main ===" in out
    assert "TOTAL so far: $7.8750" in out


def test_to_n_forecast_shows_both_tiers(project, capsys):
    """The extrapolation is forward-looking, so it still quotes both transports."""
    write_cache(project, "topics_main", [record("a")])
    run_cost(project, to_n=10)
    out = capsys.readouterr().out
    assert "for 10 calls: $52.50 sync / $26.25 batch" in out


def test_latest_record_per_cache_key_wins(project, capsys):
    """A re-run appends; only the newest record for a cache key counts, so cost isn't doubled."""
    write_cache(project, "topics_main", [record("a"), record("a", api="batch")])
    run_cost(project)
    assert "TOTAL so far: $2.6250" in capsys.readouterr().out


def test_unknown_model_reported_not_crashed(project, capsys):
    write_cache(project, "topics_main",
                [{"cache_key": "a", "model": "gpt-nope", "reasoning_effort": "medium",
                  "usage": USAGE}])
    run_cost(project)
    out = capsys.readouterr().out
    assert "No pricing for model" in out
    assert "TOTAL so far: $0.0000" in out


def test_no_cache_says_nothing_ran(project, capsys):
    run_cost(project)
    assert "nothing has run" in capsys.readouterr().out


# --- pricing table ---------------------------------------------------------------------------

def test_pricing_matches_published_rates():
    """Pinned to https://developers.openai.com/api/docs/pricing (checked 2026-07-27). If OpenAI
    reprices, this fails and defaults/pricing.yaml is the one place to fix."""
    from transcript_toolkit.core.cost import pricing
    expected = {                     # model: (input, cached, output) per 1M tokens, standard
        "gpt-5.6-sol":   (5.00, 0.50, 30.00),
        "gpt-5.6-terra": (2.50, 0.25, 15.00),
        "gpt-5.6-luna":  (1.00, 0.10, 6.00),
        "gpt-5.5":       (5.00, 0.50, 30.00),
        "gpt-5.4":       (2.50, 0.25, 15.00),
        "gpt-5.4-mini":  (0.75, 0.075, 4.50),
        "gpt-5.4-nano":  (0.20, 0.02, 1.25),
    }
    table = pricing()
    for model, (inp, cached, out) in expected.items():
        rates = table[model]["standard"]
        assert (rates["input"], rates["cached"], rates["output"]) == (inp, cached, out), model
        batch = table[model]["batch"]        # the Batch API tier is exactly half of standard
        assert (batch["input"], batch["cached"], batch["output"]) == (inp / 2, cached / 2, out / 2), model


def test_every_default_model_is_priced():
    """A model in the shipped config with no pricing entry would break cost estimation at the
    confirmation prompt — i.e. right when someone is about to spend money."""
    import yaml
    from transcript_toolkit.core.cost import pricing
    from importlib import resources
    cfg = yaml.safe_load(
        (resources.files("transcript_toolkit") / "defaults" / "scaffold" / "config.yaml").read_text())
    table = pricing()
    used = {v["model"] for v in cfg.values() if isinstance(v, dict) and "model" in v}
    assert used, "no models found in the scaffold config"
    assert used <= set(table), f"unpriced model(s): {sorted(used - set(table))}"
