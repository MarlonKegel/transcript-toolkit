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
