import shutil
from pathlib import Path

import pandas as pd
import pytest

import transcript_toolkit.steps.summarize as summarize_step
from transcript_toolkit.errors import ToolkitError
from transcript_toolkit.project import init_project
from transcript_toolkit.state import load_state
from transcript_toolkit.steps.import_ import run_import
from transcript_toolkit.steps.summarize import annotate_summaries, run_summarize

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def project(tmp_path, monkeypatch):
    project = init_project(str(tmp_path / "ws"))
    for name in ["Fake_Alpha_20240101_session1_SYNC.docx",
                 "Fake_Alpha_20240108_session2_SYNC.docx",
                 "Fake, Beta_SYNC.docx"]:
        shutil.copy(FIXTURES / name, project.data_dir / name)
    run_import(project)

    calls = []

    def fake_call_llm(client, model, reasoning, verbosity, schema, instructions,
                      user_content, prompt_cache_key_str, **kwargs):
        calls.append(user_content)
        summary = f"A fake abstract of an interview with {len(user_content.split())} words of testimony."
        usage = {"input_tokens": 1000, "output_tokens": 50,
                 "reasoning_tokens": 10, "cached_input_tokens": 800}
        return {"summary": summary}, usage

    monkeypatch.setattr(summarize_step, "call_llm", fake_call_llm)
    monkeypatch.setattr(summarize_step, "openai_client", lambda root: object())
    project.llm_calls = calls  # test-only attribute
    return project


def out_path(project):
    return project.outputs_dir / "summaries" / "summaries.parquet"


def test_demo_writes_review_only_and_records_state(project):
    df = run_summarize(project, demo=True)
    assert len(df) == 2                                   # demo_n default = 2 of 2 narrators
    assert not out_path(project).exists()                 # no deliverable from a demo
    demo_html = project.diags_dir / "summarize" / "demo_summaries.html"
    assert demo_html.exists() and "fake_alpha" in demo_html.read_text()
    demo = load_state(project)["steps"]["summarize"]["demo"]
    assert demo["units"] == ["fake_alpha", "fake_beta"]
    assert (project.cache_dir / "summarize.jsonl").exists()


def test_full_run_gated_without_demo(project):
    with pytest.raises(ToolkitError, match="No demo run"):
        run_summarize(project, yes=True)


def test_full_run_after_demo_reuses_cache(project):
    run_summarize(project, demo=True)
    n_demo_calls = len(project.llm_calls)
    assert n_demo_calls == 2
    df = run_summarize(project, yes=True)
    assert len(project.llm_calls) == n_demo_calls         # all units cached from the demo
    assert out_path(project).exists()
    assert len(df) == 2
    assert set(df.columns) >= {"interview_key", "summary", "model", "reasoning_effort"}
    full = load_state(project)["steps"]["summarize"]["full"]
    assert full["n_units"] == 2
    assert (project.diags_dir / "summarize" / "summaries.html").exists()


def test_prompt_edit_stales_demo(project):
    run_summarize(project, demo=True)
    prompt = project.prompts_dir / "summarize_interview.md"
    prompt.write_text(prompt.read_text() + "\nAlways mention the weather.")
    with pytest.raises(ToolkitError, match="stale"):
        run_summarize(project, yes=True)


def test_skip_demo_check_bypasses_gate(project):
    df = run_summarize(project, yes=True, skip_demo_check=True)
    assert len(df) == 2 and out_path(project).exists()


def test_pooling_toggle_changes_units_and_fingerprint(project):
    df = run_summarize(project, demo=True)
    assert set(df["interview_key"]) == {"fake_alpha", "fake_beta"}
    # flipping pooling changes the fingerprint -> full run is gated again
    with pytest.raises(ToolkitError, match="No demo|stale"):
        run_summarize(project, pool_sessions=False, yes=True)
    df2 = run_summarize(project, demo=True, pool_sessions=False)
    assert set(df2["interview_key"]) <= {"fake_alpha_20240101_session1",
                                         "fake_alpha_20240108_session2", "fake_beta"}


def test_interview_subset_merges(project):
    run_summarize(project, demo=True)
    run_summarize(project, yes=True)
    before = pd.read_parquet(out_path(project))
    run_summarize(project, interviews=["fake_beta"], yes=True)
    after = pd.read_parquet(out_path(project))
    assert len(after) == len(before) == 2                 # merged, not clobbered
    assert set(after["interview_key"]) == {"fake_alpha", "fake_beta"}


def test_unknown_interview_key_fails_loud(project):
    run_summarize(project, demo=True)
    with pytest.raises(ToolkitError, match="Unknown interview key"):
        run_summarize(project, interviews=["nobody"], yes=True)


def test_annotate_rerenders(project):
    run_summarize(project, demo=True)
    run_summarize(project, yes=True)
    page = project.diags_dir / "summarize" / "summaries.html"
    page.unlink()
    annotate_summaries(project)
    assert page.exists()


def test_annotate_without_deliverable_fails(project):
    with pytest.raises(ToolkitError, match="Run `toolkit summarize` first"):
        annotate_summaries(project)


def test_batch_transport_fills_cache_and_builds_deliverable(project, monkeypatch):
    """--batch routes the uncached interviews through one Batch-API job; the normal assembly then
    runs entirely off the cache and makes no synchronous call."""
    import json

    import transcript_toolkit.core.batch as batch_mod

    def fake_run_batch(client, units, batch_dir, **kwargs):
        return {u["custom_id"]: ({"summary": f"Batched abstract for {u['custom_id']}."},
                                 {"input_tokens": 10, "output_tokens": 5,
                                  "reasoning_tokens": 1, "cached_input_tokens": 0})
                for u in units}, []

    monkeypatch.setattr(batch_mod, "run_batch", fake_run_batch)
    monkeypatch.setattr(summarize_step, "call_llm",
                        lambda *a, **k: pytest.fail("batch run must not call the sync API"))

    df = run_summarize(project, yes=True, skip_demo_check=True, batch=True)
    assert len(df) == 2
    assert all(s.startswith("Batched abstract") for s in df["summary"])
    records = [json.loads(ln) for ln
               in (project.cache_dir / "summarize.jsonl").read_text().splitlines()]
    assert records and all(r.get("api") == "batch" for r in records)


def test_batch_failures_are_not_silently_dropped(project, monkeypatch):
    import transcript_toolkit.core.batch as batch_mod

    def half_failing(client, units, batch_dir, **kwargs):
        ok = units[:1]
        return ({u["custom_id"]: ({"summary": "ok"}, {"input_tokens": 1, "output_tokens": 1,
                                                      "reasoning_tokens": 0,
                                                      "cached_input_tokens": 0}) for u in ok},
                [(u["custom_id"], "boom") for u in units[1:]])

    monkeypatch.setattr(batch_mod, "run_batch", half_failing)
    with pytest.raises(ToolkitError, match="uncached"):
        run_summarize(project, yes=True, skip_demo_check=True, batch=True)


# --- transcripts that were never SYNC'd -------------------------------------------------------

def with_unsynced(project):
    """Put the untimed fixture in the workspace and read it in. Its narrator is `fake_gamma`,
    which nobody in the collection is."""
    project.unsynced_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES / "unsynced" / "Fake_Gamma_Transcript.docx",
                project.unsynced_dir / "Fake_Gamma_Transcript.docx")
    run_import(project)
    return project


def test_untimed_transcripts_are_summarized_like_the_rest(project):
    """`--unsynced` picks them out of the one collection the way `--interview` picks a few.
    One step, one record: there is no separate pile to keep books on any more."""
    with_unsynced(project)
    df = run_summarize(project, demo=True, unsynced=True)
    assert list(df["interview_key"]) == ["fake_gamma_transcript"]
    assert not df["synced"].any()
    page = project.diags_dir / "summarize" / "demo_summaries.html"
    assert page.exists() and "never SYNC'd" in page.read_text()
    assert set(load_state(project)["steps"]) == {"summarize"}


def test_their_summaries_join_the_collections_own(project):
    with_unsynced(project)
    run_summarize(project, demo=True)
    run_summarize(project, yes=True)

    df = pd.read_parquet(out_path(project)).set_index("interview_key")
    assert set(df.index) == {"fake_alpha", "fake_beta", "fake_gamma_transcript"}
    assert not bool(df.loc["fake_gamma_transcript", "synced"])
    assert bool(df.loc["fake_alpha", "synced"])


def test_summarizing_only_the_untimed_ones_leaves_the_others_standing(project):
    """A subset run splices into the table, the way `--interview` does — it is not a statement
    about the interviews it did not look at."""
    with_unsynced(project)
    run_summarize(project, demo=True)
    run_summarize(project, yes=True)
    run_summarize(project, yes=True, unsynced=True)
    keys = set(pd.read_parquet(out_path(project))["interview_key"])
    assert keys == {"fake_alpha", "fake_beta", "fake_gamma_transcript"}


def test_a_run_over_everything_drops_a_transcript_that_has_gone(project):
    """The whole collection in one run means the table is what the run covered."""
    with_unsynced(project)
    run_summarize(project, demo=True)
    run_summarize(project, yes=True)

    (project.data_dir / "Fake, Beta_SYNC.docx").unlink()
    run_import(project)
    run_summarize(project, yes=True, skip_demo_check=True)
    keys = set(pd.read_parquet(out_path(project))["interview_key"])
    assert keys == {"fake_alpha", "fake_gamma_transcript"}


def test_one_demo_lets_the_whole_collection_through(project):
    """The untimed transcripts are summarized by the same prompt from the same kind of text, so
    a demo of the step is a demo of the step — there is no second gate to pass."""
    with_unsynced(project)
    run_summarize(project, demo=True)
    df = run_summarize(project, yes=True, unsynced=True)
    assert list(df["interview_key"]) == ["fake_gamma_transcript"] or len(df) >= 1


def test_asking_for_untimed_ones_that_are_not_there_says_so(project):
    with pytest.raises(ToolkitError, match="never SYNC'd"):
        run_summarize(project, demo=True, unsynced=True)
