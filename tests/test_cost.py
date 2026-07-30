"""`toolkit cost` is the project's cost report: money actually spent, per step and in total.

Each group is priced at the tier it was really billed at, decided by the `api` field the batch
path stamps on its records. Every cached call counts, because every cached call was paid for.
"""
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
    assert "Project cost report" in out
    # each step named the way state.json names it, so a topic list is its own line
    assert "label: $5.2500" in out and "topics:main: $2.6250" in out
    assert "TOTAL so far: $7.8750" in out


def test_to_n_forecast_shows_both_tiers(project, capsys):
    """The extrapolation is forward-looking, so it still quotes both transports."""
    write_cache(project, "topics_main", [record("a")])
    run_cost(project, to_n=10)
    out = capsys.readouterr().out
    assert "for 10 calls: $52.50 sync / $26.25 batch" in out


def test_every_call_ever_made_is_counted(project, capsys):
    """This is a report of what was spent, not of what the current results cost. A step only
    appends a record when it actually calls the API, so two records for one cache key are two
    calls that were both paid for — even though only the later one is used from here on."""
    write_cache(project, "topics_main", [record("a"), record("a", api="batch")])
    run_cost(project)
    out = capsys.readouterr().out
    assert "TOTAL so far: $7.8750" in out
    assert "2 calls" in out


def test_demos_and_abandoned_attempts_are_in_the_total(project, capsys):
    """Records left behind by a prompt that has since been rewritten have different cache keys
    and are still money that left the account."""
    write_cache(project, "clip", [record("old-prompt"), record("new-prompt")])
    run_cost(project)
    assert "TOTAL so far: $10.5000" in capsys.readouterr().out


def test_the_report_is_the_same_figures_as_data(project):
    """The app draws its cost report from this, so the printed one and the drawn one cannot
    disagree about what a project has cost."""
    from transcript_toolkit.steps.cost import spend_report, spent_on

    write_cache(project, "label", [record("a")])
    write_cache(project, "topics_main", [record("b", api="batch")])
    report = spend_report(project)

    assert report["total_usd"] == pytest.approx(7.875)
    assert report["calls"] == 2
    assert report["by_tier"] == pytest.approx({"standard": 5.25, "batch": 2.625})
    assert spent_on(report, "topics:main")["usd"] == pytest.approx(2.625)
    assert spent_on(report, "summarize") is None
    assert [e["key"] for e in report["steps"]] == ["label", "topics:main"]


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


# --- pricing provenance ----------------------------------------------------------------------

def test_price_table_states_when_it_was_verified():
    """Prices carry their own age, because nothing updates them automatically."""
    import datetime
    from transcript_toolkit.core.cost import _price_file
    data = _price_file()
    assert isinstance(data["verified"], datetime.date)
    assert data["source"].startswith("https://")


def test_no_note_while_prices_are_fresh(monkeypatch):
    import datetime
    from transcript_toolkit.core import cost as c
    monkeypatch.setattr(c, "_price_file", lambda: {"verified": datetime.date.today(),
                                                   "source": "https://example.test", "models": {}})
    assert c.pricing_note() is None


def test_note_appears_once_prices_are_old(monkeypatch):
    import datetime
    from transcript_toolkit.core import cost as c
    old = datetime.date.today() - datetime.timedelta(days=c.STALE_AFTER_DAYS + 40)
    monkeypatch.setattr(c, "_price_file", lambda: {"verified": old,
                                                   "source": "https://example.test", "models": {}})
    note = c.pricing_note()
    assert note and old.isoformat() in note
    assert "if these look wrong" in note and "https://example.test" in note


def test_unpriced_model_gives_unknown_not_a_crash():
    """A model newer than the toolkit's price table must not block a run at the confirmation
    prompt — the estimate is advisory, so 'unknown' is the right answer."""
    from transcript_toolkit.core.cost import estimate_pair
    cache = {"k": {"fingerprint": "fp", "model": "gpt-9.9-unreleased",
                   "usage": {"input_tokens": 1000, "output_tokens": 100,
                             "reasoning_tokens": 0, "cached_input_tokens": 0}}}
    assert estimate_pair(cache, "fp", "gpt-9.9-unreleased", 10) is None
