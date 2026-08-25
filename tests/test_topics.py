import shutil
from pathlib import Path

import pandas as pd
import pytest

import transcript_toolkit.steps.topics.tag as tag_step
from transcript_toolkit.core.tables import clips_path, write_deliverable
from transcript_toolkit.core import thresholds
from transcript_toolkit.errors import ToolkitError
from transcript_toolkit.project import init_project
from transcript_toolkit.state import load_state, rolled_up_with
from transcript_toolkit.steps.import_ import run_import
from transcript_toolkit.steps.topics import (
    annotate_topics,
    run_topics_rollup,
    run_topics_tag,
    run_topics_thresholds,
)

FIXTURES = Path(__file__).parent / "fixtures"

TOPICS_CSV = ('name,description\n'
              'Education,"Schooling, universities, and training."\n'
              'Career,"Jobs, organizations, and professional life."\n'
              'Family,"Family, home, and community life."\n')


def synthesize_clips(project) -> pd.DataFrame:
    """Clips deliverable from the imported fixture paragraphs: 2-3 clips per interview over
    contiguous paragraph ranges (mimics what `toolkit clip` would produce)."""
    paragraphs = pd.read_parquet(project.paragraphs_path)
    rows = []
    for iid, g in paragraphs.groupby("interview_id"):
        g = g.sort_values("paragraph_idx")
        idxs = g["paragraph_idx"].tolist()
        n_chunks = 3 if len(idxs) >= 9 else 2
        size = -(-len(idxs) // n_chunks)
        chunks = [idxs[i:i + size] for i in range(0, len(idxs), size)]
        for n, chunk in enumerate(chunks, start=1):
            sub = g[g["paragraph_idx"].isin(chunk)]
            rows.append({
                "interview_id": iid, "clip_id": f"{iid}_{n:04d}",
                "start_paragraph_idx": int(chunk[0]), "end_paragraph_idx": int(chunk[-1]),
                "n_paragraphs": len(chunk), "total_words": int(sub["word_count"].sum()),
                "start_ts": sub.iloc[0]["turn_time_start"],
                "end_ts": sub.iloc[-1]["turn_time_start"],
                "duration_seconds": 60.0,
            })
    clips = pd.DataFrame(rows)
    write_deliverable(clips, clips_path(project), sort_by="clip_id")
    return clips


@pytest.fixture
def project(tmp_path, monkeypatch):
    project = init_project(str(tmp_path / "ws"))
    for name in ["Fake_Alpha_20240101_session1_SYNC.docx",
                 "Fake_Alpha_20240108_session2_SYNC.docx",
                 "Fake, Beta_SYNC.docx"]:
        shutil.copy(FIXTURES / name, project.data_dir / name)
    run_import(project)
    project.clips = synthesize_clips(project)                  # test-only attribute
    (project.topics_dir / "main.csv").write_text(TOPICS_CSV)   # scaffold config points here

    calls = []

    def fake_call_llm(client, model, reasoning, verbosity, schema, instructions,
                      user_content, prompt_cache_key_str, **kwargs):
        calls.append(instructions)
        justify = "evidence" in schema["schema"]["properties"]
        parsed = {"scores": {"education": 2, "career": 1, "family": 0}}
        if justify:
            parsed["evidence"] = [
                {"topic_id": "education", "justification": "The clip discusses schooling."},
                {"topic_id": "career", "justification": "A job is mentioned."},
            ]
        usage = {"input_tokens": 1000, "output_tokens": 50,
                 "reasoning_tokens": 10, "cached_input_tokens": 800}
        return parsed, usage

    monkeypatch.setattr(tag_step, "call_llm", fake_call_llm)
    monkeypatch.setattr(tag_step, "openai_client", lambda root: object())
    project.llm_calls = calls                                  # test-only attribute
    return project


def set_entry(project, **overrides):
    """Set topics.sets.main explicitly. (Tests don't need the scaffold's comments preserved —
    test_taxonomy.py covers that the real auto-registration keeps them.)"""
    import yaml
    cfg = yaml.safe_load(project.config_path.read_text())
    cfg["topics"]["sets"] = {"main": {"file": "topics/main.csv", **overrides}}
    project.config_path.write_text(yaml.safe_dump(cfg, sort_keys=False))


def wide_path(project):
    return project.outputs_dir / "topics" / "main_clip_topics_wide.parquet"


def long_path(project):
    return project.outputs_dir / "topics" / "main_clip_topics_long.parquet"


# --- tag ---------------------------------------------------------------------------------


def test_demo_writes_review_and_state_only(project):
    df = run_topics_tag(project, "main", demo=True)
    assert len(df) == len(project.clips)                       # demo_n_clips=50 >= corpus
    assert not wide_path(project).exists()                     # no deliverable from a demo
    page = project.diags_dir / "topics" / "main_demo.html"
    text = page.read_text()
    assert "The clip discusses schooling." in text             # justifications ON for demos
    assert df["clip_id"].iloc[0] in text
    demo = load_state(project)["steps"]["topics:main"]["demo"]
    assert sorted(demo["units"]) == sorted(project.clips["clip_id"])
    assert (project.cache_dir / "topics_main.jsonl").exists()


def test_demo_sample_n_and_seed_override(project):
    df = run_topics_tag(project, "main", demo=True, sample_n=3, seed=1)
    assert len(df) == 3


def test_full_run_gated_without_demo(project):
    with pytest.raises(ToolkitError, match="No demo run"):
        run_topics_tag(project, "main", yes=True)


def test_justify_on_demo_approves_justify_off_full_run(project):
    run_topics_tag(project, "main", demo=True)                         # justify defaults ON
    n_demo = len(project.llm_calls)
    assert n_demo == len(project.clips)
    df = run_topics_tag(project, "main", yes=True)                     # justify defaults OFF
    # The gate fingerprints the justify-OFF base instructions, so the justify-on demo is
    # current here — but the actual instructions differ, so the full run makes fresh calls.
    assert len(project.llm_calls) == 2 * n_demo
    assert len(df) == len(project.clips)
    long_df = pd.read_parquet(long_path(project))
    assert (long_df["justification"] == "").all()              # no rationales on the full run
    full = load_state(project)["steps"]["topics:main"]["full"]
    assert full["n_units"] == len(project.clips)
    run_topics_tag(project, "main", yes=True)                          # re-run: everything cached
    assert len(project.llm_calls) == 2 * n_demo


def test_a_full_run_leaves_pages_to_read(project):
    """The same rule as every other step: a run that has been paid for leaves something on disk
    to check it by, without having to know that `annotate` exists."""
    run_topics_tag(project, "main", demo=True)
    assert (project.diags_dir / "topics" / "main_demo.html").exists()
    run_topics_tag(project, "main", yes=True)
    assert (project.diags_dir / "topics" / "main_index.html").exists()
    assert list((project.diags_dir / "topics").glob("main_fake_*.html"))


def test_topic_spreadsheet_edit_stales_demo(project):
    run_topics_tag(project, "main", demo=True)
    (project.topics_dir / "main.csv").write_text(
        TOPICS_CSV + 'Travel,"Journeys and migration."\n')
    with pytest.raises(ToolkitError, match="stale"):
        run_topics_tag(project, "main", yes=True)


def test_deliverable_schemas(project):
    run_topics_tag(project, "main", demo=True)
    run_topics_tag(project, "main", yes=True)
    wide = pd.read_parquet(wide_path(project))
    assert list(wide.columns) == ["clip_id", "interview_id", "education", "career", "family",
                                  "top_score", "top_topics", "n_topics_assigned", "fits_any",
                                  "model", "reasoning_effort"]
    assert wide_path(project).with_suffix(".csv").exists()
    row = wide.iloc[0]
    assert row["top_score"] == 2 and row["top_topics"] == "education"
    assert row["n_topics_assigned"] == 1 and bool(row["fits_any"])
    long = pd.read_parquet(long_path(project))
    assert list(long.columns) == ["clip_id", "interview_id", "topic_id", "topic_name",
                                  "score", "justification"]
    assert len(long) == len(project.clips) * 3                 # one row per clip x topic


def test_interview_subset_merges(project):
    run_topics_tag(project, "main", demo=True)
    run_topics_tag(project, "main", yes=True)
    before = pd.read_parquet(wide_path(project))
    run_topics_tag(project, "main", interviews=["fake_beta"], yes=True)
    after = pd.read_parquet(wide_path(project))
    assert len(after) == len(before)                           # merged, not clobbered
    assert after["clip_id"].is_unique
    long_after = pd.read_parquet(long_path(project))
    assert len(long_after) == len(before) * 3


def test_unknown_interview_fails_loud(project):
    run_topics_tag(project, "main", demo=True)
    with pytest.raises(ToolkitError, match="Unknown interview id"):
        run_topics_tag(project, "main", interviews=["nobody"], yes=True)


def test_per_set_prompt_override(project):
    # A set may bring its own rubric via config sets.<set>.prompt (e.g. OSF's filter set).
    (project.prompts_dir / "tag_topics_strict.md").write_text(
        "STRICT RUBRIC: tag only specific and substantive mentions.")
    set_entry(project, prompt="tag_topics_strict.md")
    run_topics_tag(project, "main", demo=True)
    assert any("STRICT RUBRIC" in i for i in project.llm_calls)
    # the default prompt is no longer part of the instructions for this set
    default_text = (project.prompts_dir / "tag_topics.md").read_text().strip()
    assert all(default_text not in i for i in project.llm_calls)


def test_a_set_runs_on_its_own_model_and_reasoning(project):
    """Two topic lists are two pieces of work: a fine-grained list may want a stronger model than
    a coarse one, and neither should have to dictate the other's."""
    set_entry(project, model="gpt-5.4-nano", reasoning="high")
    cfg, tset, _justify, _instructions, _fp = tag_step._context(project, "main", None, True)
    assert (cfg["model"], cfg["reasoning"]) == ("gpt-5.4-nano", "high")
    assert tset.overrides == {"model": "gpt-5.4-nano", "reasoning": "high"}


def test_a_set_without_overrides_runs_on_the_steps_settings(project):
    set_entry(project)
    cfg, tset, _j, _i, _f = tag_step._context(project, "main", None, True)
    assert tset.overrides == {}
    assert cfg["model"] == "gpt-5.6-luna"          # the scaffold's topics.model


def test_a_sets_own_model_stales_only_that_sets_demo(project):
    """The fingerprint already covers the model, so changing one list's model asks for a fresh
    demo of that list and leaves the others alone."""
    set_entry(project)
    _, _, _, _, before = tag_step._context(project, "main", None, True)
    set_entry(project, model="gpt-5.4-nano")
    _, _, _, _, after = tag_step._context(project, "main", None, True)
    assert before != after


def test_an_impossible_reasoning_level_for_a_set_is_refused(project):
    set_entry(project, reasoning="enormous")
    with pytest.raises(ToolkitError, match="Unknown reasoning level"):
        tag_step._context(project, "main", None, True)


def test_unknown_set_fails_loud(project):
    with pytest.raises(ToolkitError, match="Unknown topic set"):
        run_topics_tag(project, set_name="nope", demo=True)


# --- rollup ------------------------------------------------------------------------------


def write_hand_wide(project):
    """Hand-built clip-level wide deliverable with known assigned shares.

    Narrator fake_alpha (2 sessions, 4 clips): education assigned in 2 (50%),
    career in 1 (25%), family in 0. Narrator fake_beta (4 clips): education in all 4.
    Corpus clip-frequency: education 6, career 1, family 0.
    """
    rows = []

    def clip(iid, n, e, c, f):
        rows.append({"clip_id": f"{iid}_{n:04d}", "interview_id": iid,
                     "education": e, "career": c, "family": f})

    clip("fake_alpha_20240101_session1", 1, 2, 0, 0)
    clip("fake_alpha_20240101_session1", 2, 2, 1, 0)
    clip("fake_alpha_20240108_session2", 1, 0, 2, 1)
    clip("fake_alpha_20240108_session2", 2, 0, 0, 0)
    for n in range(1, 5):
        clip("fake_beta", n, 2, 0, 0)
    write_deliverable(pd.DataFrame(rows), wide_path(project), sort_by="clip_id")


def interview_paths(project):
    out = project.outputs_dir / "topics"
    return out / "main_interview_topics_wide.parquet", out / "main_interview_topics_long.parquet"


def test_rollup_flat(project):
    write_hand_wide(project)
    set_entry(project, rollup={"method": "flat", "threshold_pct": 30})
    # one bar for every topic: alpha education 50% >= 30 tagged, career 25% < 30 not
    wide = run_topics_rollup(project, "main").set_index("interview_key")
    assert list(wide.index) == ["fake_alpha", "fake_beta"]     # sessions pooled per narrator
    assert wide.loc["fake_alpha", "topics"] == "education"
    assert wide.loc["fake_alpha", "n_topics"] == 1
    assert wide.loc["fake_alpha", "n_sessions"] == 2 and wide.loc["fake_alpha", "n_clips"] == 4
    assert wide.loc["fake_beta", "topics"] == "education"
    wide_p, long_p = interview_paths(project)
    assert wide_p.exists() and long_p.exists() and long_p.with_suffix(".csv").exists()
    long = pd.read_parquet(long_p)
    row = long[(long["interview_key"] == "fake_alpha") & (long["topic_id"] == "career")].iloc[0]
    assert row["pct_clips"] == 25.0 and row["threshold_pct"] == 30.0 and not row["tagged"]
    assert row["n_clips_assigned"] == 1 and row["n_clips_total"] == 4


def test_rollup_defaults_to_rarity_bins(project):
    """A set nobody has configured rolls up the recommended way: 5 rarity bands over 10-30%."""
    write_hand_wide(project)
    # frequencies [education 6, career 1, family 0] over 5 equal-width bands: education lands in
    # the top band, career and family in the bottom one. The bars fan out from the midpoint
    # (20%) by the spread of the seen frequencies — reach (6-1)/6 = 5/6, so the top band bar is
    # 20 + 5/6*10 = 28.33% and the bottom 11.67%. Alpha's career is 25% of its clips — under a
    # flat 30% bar it would be dropped; here it clears its own.
    wide = run_topics_rollup(project, "main").set_index("interview_key")
    assert wide.loc["fake_alpha", "topics"] == "education|career"
    _, long_p = interview_paths(project)
    long = pd.read_parquet(long_p)
    bars = long.drop_duplicates("topic_id").set_index("topic_id")["threshold_pct"]
    assert bars["education"] == 28.33 and bars["career"] == 11.67 and bars["family"] == 11.67


def test_rollup_binned_hand_computed(project):
    write_hand_wide(project)
    set_entry(project, rollup={"method": "freq_width", "bins": 2, "range": [10, 30]})
    # 2 equal-width bins over frequencies [6, 1, 0]: family(0) and career(1) fall in the rare
    # band, education(6) in the common one. Reach = (6-1)/6 = 5/6 of the [10, 30] ladder around
    # its 20% midpoint: rare bar 11.67%, common bar 28.33%. So alpha's career (25% of clips)
    # clears its bar while education still needs (and clears) its higher one.
    wide = run_topics_rollup(project, "main").set_index("interview_key")
    assert wide.loc["fake_alpha", "topics"] == "education|career"
    assert wide.loc["fake_alpha", "n_topics"] == 2
    assert wide.loc["fake_beta", "topics"] == "education"
    _, long_p = interview_paths(project)
    long = pd.read_parquet(long_p)
    career = long[(long["interview_key"] == "fake_alpha") & (long["topic_id"] == "career")].iloc[0]
    assert career["threshold_pct"] == 11.67 and career["tagged"]
    edu = long[long["topic_id"] == "education"].iloc[0]
    assert edu["threshold_pct"] == 28.33


def test_rollup_thresholds_spread_only_as_far_as_the_frequencies_do():
    """The default method adapts to the distribution: equally-common topics all face one
    threshold, near-equal counts get near-equal thresholds instead of being stretched to the
    extremes, and a topic that never comes up does not stretch the ladder for the ones that do."""
    rule = thresholds.Rollup()                            # freq_width, 5 bins, 10-30%
    equal = rule.thresholds(pd.Series({"a": 12, "b": 12, "c": 12}))
    assert set(equal) == {20.0}                           # dead flat at the midpoint
    close = rule.thresholds(pd.Series({"a": 10, "b": 11}))
    assert list(close) == [19.09, 20.91]                  # a one-count difference stays minor
    skewed = rule.thresholds(pd.Series({"a": 1, "b": 50}))
    assert list(skewed) == [10.2, 29.8]                   # a real skew uses almost the full ladder
    unseen = rule.thresholds(pd.Series({"a": 12, "b": 12, "zero": 0}))
    assert unseen["a"] == unseen["b"] == 20.0             # frequency-0 items don't stretch it


def test_rollup_reads_the_older_spelling(project):
    """Projects made before the methods existed said `scheme: binned` with the bars written out.
    They are still in use, so they still roll up the same way."""
    write_hand_wide(project)
    set_entry(project, rollup={"scheme": "binned", "thresholds": [10, 30]})
    wide = run_topics_rollup(project, "main").set_index("interview_key")
    assert wide.loc["fake_alpha", "topics"] == "education|career"

    set_entry(project, rollup={"scheme": "flat", "threshold_pct": 30})
    wide = run_topics_rollup(project, "main").set_index("interview_key")
    assert wide.loc["fake_alpha", "topics"] == "education"


def test_a_hand_written_threshold_list_survives_being_recorded(project):
    """A rollup records the rule it ran with, and the decision aid reads that back. Describing a
    hand-written list by bins and range instead would regularise it — and a one-element list would
    come back as a range with no width, which is refused outright."""
    write_hand_wide(project)
    set_entry(project, rollup={"method": "freq_width", "thresholds": [50]})
    run_topics_rollup(project, "main")
    assert rolled_up_with(project, "topics:main") == {"method": "freq_width", "thresholds": [50]}
    run_topics_thresholds(project, "main")               # used to crash on the read-back

    set_entry(project, rollup={"method": "freq_width", "thresholds": [10, 12.5, 30]})
    run_topics_rollup(project, "main")
    assert thresholds.parse(rolled_up_with(project, "topics:main"), "x").bars() == [10, 12.5, 30]


def test_rollup_schemas(project):
    write_hand_wide(project)
    run_topics_rollup(project, "main")
    wide_p, long_p = interview_paths(project)
    assert list(pd.read_parquet(wide_p).columns) == [
        "interview_key", "n_sessions", "n_clips", "education", "career", "family",
        "topics", "n_topics"]
    assert list(pd.read_parquet(long_p).columns) == [
        "interview_key", "topic_id", "topic_name", "n_clips_assigned", "n_clips_total",
        "pct_clips", "threshold_pct", "tagged"]


def test_rollup_without_tag_fails(project):
    with pytest.raises(ToolkitError, match="topics tag"):
        run_topics_rollup(project, "main")


# --- thresholds aid + annotate -------------------------------------------------------------


def test_thresholds_aid_compares_every_method(project, capsys):
    write_hand_wide(project)
    run_topics_thresholds(project, "main")
    out = capsys.readouterr().out
    assert "nothing has been rolled up yet" in out
    for method in ("freq_width", "equal_count", "flat"):
        assert (project.diags_dir / "topics" / "plots" / f"main_{method}.png").exists()

    page = (project.diags_dir / "topics" / "main_thresholds.html").read_text()
    for method in thresholds.METHODS:                   # one foldable panel per method
        assert f"<summary>{thresholds.method_label(method, thresholds.TOPICS)}" in page
    assert 'src="plots/main_freq_width.png"' in page
    # one explanation, up top, not folded away behind a summary like the panels of plots
    assert page.count("<summary>") == len(thresholds.METHODS) + 1     # + the table
    assert "This is where you decide what counts as enough" in page


def test_nothing_is_marked_as_yours_until_you_have_rolled_up(project):
    """A rule sitting in config.yaml is a plan. Marking it as what your results were built with
    is a lie until a rollup has actually been run with it — which is exactly the moment somebody
    changes the setting, re-runs the comparison, and sees the old answer still labelled theirs."""
    write_hand_wide(project)
    run_topics_thresholds(project, "main")
    page = (project.diags_dir / "topics" / "main_thresholds.html").read_text()
    assert "what your results were built with" not in page

    set_entry(project, rollup={"method": "flat", "threshold_pct": 30})
    run_topics_rollup(project, "main")
    run_topics_thresholds(project, "main")
    page = (project.diags_dir / "topics" / "main_thresholds.html").read_text()
    assert "what your results were built with" in page
    # ...and it is the flat panel that carries it, while freq-width keeps saying "recommended"
    flat_at = page.index(thresholds.method_label("flat"))
    assert "what your results were built with" in page[flat_at:flat_at + 300]
    recommended_at = page.index(thresholds.method_label(thresholds.RECOMMENDED))
    assert "recommended" in page[recommended_at:recommended_at + 300]


def test_the_recommended_tag_survives_being_the_one_you_use(project):
    write_hand_wide(project)
    run_topics_rollup(project, "main")                  # the scaffold default is freq-width
    run_topics_thresholds(project, "main")
    page = (project.diags_dir / "topics" / "main_thresholds.html").read_text()
    at = page.index(thresholds.method_label(thresholds.RECOMMENDED))
    assert "recommended" in page[at:at + 300]
    assert "what your results were built with" in page[at:at + 300]


def test_thresholds_aid_takes_what_to_compare(project):
    write_hand_wide(project)
    run_topics_thresholds(project, "main", bins=[3], ranges=[(20.0, 40.0)], flat=[50.0])
    page = (project.diags_dir / "topics" / "main_thresholds.html").read_text()
    assert "3 bins · 20–40%" in page and "50% for every topic" in page
    assert "9 bins" not in page


def test_what_your_results_used_is_drawn_even_if_you_did_not_ask_for_it(project):
    """It is the thing being compared against, so it has to be in the grid — folded into the
    axes rather than tacked on the end, so it can be read along both dimensions."""
    write_hand_wide(project)
    set_entry(project, rollup={"method": "freq_width", "bins": 3, "range": [15, 35]})
    run_topics_rollup(project, "main")
    run_topics_thresholds(project, "main", bins=[5], ranges=[(10.0, 30.0)])
    page = (project.diags_dir / "topics" / "main_thresholds.html").read_text()
    assert "3 bins · 15–35%" in page and "5 bins · 10–30%" in page
    assert "3 bins · 10–30%" in page and "5 bins · 15–35%" in page     # the full grid


def test_annotate_writes_per_interview_html(project):
    run_topics_tag(project, "main", demo=True)
    run_topics_tag(project, "main", yes=True)
    annotate_topics(project, "main")
    for iid in sorted(project.clips["interview_id"].unique()):
        page = project.diags_dir / "topics" / f"main_{iid}.html"
        assert page.exists()
        text = page.read_text()
        assert "Clip 1" in text and "Education" in text
    assert (project.diags_dir / "topics" / "main_index.html").exists()


def test_annotate_without_deliverable_fails(project):
    with pytest.raises(ToolkitError, match="topics tag"):
        annotate_topics(project, "main")


def test_batch_transport_fills_cache_and_builds_deliverables(project, monkeypatch):
    """--batch routes the uncached clips through one Batch-API job; scoring/assembly then runs
    entirely off the cache and makes no synchronous call."""
    import json

    import transcript_toolkit.core.batch as batch_mod

    def fake_run_batch(client, units, batch_dir, **kwargs):
        return {u["custom_id"]: ({"scores": {"education": 2, "career": 0, "family": 1}},
                                 {"input_tokens": 10, "output_tokens": 5,
                                  "reasoning_tokens": 1, "cached_input_tokens": 0})
                for u in units}, []

    monkeypatch.setattr(batch_mod, "run_batch", fake_run_batch)
    monkeypatch.setattr(tag_step, "call_llm",
                        lambda *a, **k: pytest.fail("batch run must not call the sync API"))

    df = run_topics_tag(project, "main", yes=True, skip_demo_check=True, batch=True)
    assert len(df) == len(project.clips)
    assert set(df["education"]) == {2} and set(df["family"]) == {1}
    assert wide_path(project).exists()
    records = [json.loads(ln) for ln
               in (project.cache_dir / "topics_main.jsonl").read_text().splitlines()]
    assert records and all(r.get("api") == "batch" for r in records)
