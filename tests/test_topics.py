import shutil
from pathlib import Path

import pandas as pd
import pytest

import transcript_toolkit.steps.topics.tag as tag_step
from transcript_toolkit.core.tables import clips_path, write_deliverable
from transcript_toolkit.errors import ToolkitError
from transcript_toolkit.project import init_project
from transcript_toolkit.state import load_state
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


def wide_path(project):
    return project.outputs_dir / "topics" / "main_clip_topics_wide.parquet"


def long_path(project):
    return project.outputs_dir / "topics" / "main_clip_topics_long.parquet"


# --- tag ---------------------------------------------------------------------------------


def test_demo_writes_review_and_state_only(project):
    df = run_topics_tag(project, demo=True)
    assert len(df) == len(project.clips)                       # demo_n_clips=50 >= corpus
    assert not wide_path(project).exists()                     # no deliverable from a demo
    md = project.diags_dir / "topics" / "main_demo.md"
    text = md.read_text()
    assert "The clip discusses schooling." in text             # justifications ON for demos
    assert df["clip_id"].iloc[0] in text
    demo = load_state(project)["steps"]["topics:main"]["demo"]
    assert sorted(demo["units"]) == sorted(project.clips["clip_id"])
    assert (project.cache_dir / "topics_main.jsonl").exists()


def test_demo_sample_n_and_seed_override(project):
    df = run_topics_tag(project, demo=True, sample_n=3, seed=1)
    assert len(df) == 3


def test_full_run_gated_without_demo(project):
    with pytest.raises(ToolkitError, match="No demo run"):
        run_topics_tag(project, yes=True)


def test_justify_on_demo_approves_justify_off_full_run(project):
    run_topics_tag(project, demo=True)                         # justify defaults ON
    n_demo = len(project.llm_calls)
    assert n_demo == len(project.clips)
    df = run_topics_tag(project, yes=True)                     # justify defaults OFF
    # The gate fingerprints the justify-OFF base instructions, so the justify-on demo is
    # current here — but the actual instructions differ, so the full run makes fresh calls.
    assert len(project.llm_calls) == 2 * n_demo
    assert len(df) == len(project.clips)
    long_df = pd.read_parquet(long_path(project))
    assert (long_df["justification"] == "").all()              # no rationales on the full run
    full = load_state(project)["steps"]["topics:main"]["full"]
    assert full["n_units"] == len(project.clips)
    run_topics_tag(project, yes=True)                          # re-run: everything cached
    assert len(project.llm_calls) == 2 * n_demo


def test_topic_spreadsheet_edit_stales_demo(project):
    run_topics_tag(project, demo=True)
    (project.topics_dir / "main.csv").write_text(
        TOPICS_CSV + 'Travel,"Journeys and migration."\n')
    with pytest.raises(ToolkitError, match="stale"):
        run_topics_tag(project, yes=True)


def test_deliverable_schemas(project):
    run_topics_tag(project, demo=True)
    run_topics_tag(project, yes=True)
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
    run_topics_tag(project, demo=True)
    run_topics_tag(project, yes=True)
    before = pd.read_parquet(wide_path(project))
    run_topics_tag(project, interviews=["fake_beta"], yes=True)
    after = pd.read_parquet(wide_path(project))
    assert len(after) == len(before)                           # merged, not clobbered
    assert after["clip_id"].is_unique
    long_after = pd.read_parquet(long_path(project))
    assert len(long_after) == len(before) * 3


def test_unknown_interview_fails_loud(project):
    run_topics_tag(project, demo=True)
    with pytest.raises(ToolkitError, match="Unknown interview id"):
        run_topics_tag(project, interviews=["nobody"], yes=True)


def test_unknown_set_fails_loud(project):
    with pytest.raises(ToolkitError, match="Unknown topic set.*main"):
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
    wide = run_topics_rollup(project).set_index("interview_key")
    # flat 30% (scaffold config): alpha education 50% >= 30 tagged, career 25% < 30 not
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


def test_rollup_binned_hand_computed(project):
    write_hand_wide(project)
    project.config_path.write_text(project.config_path.read_text().replace(
        "rollup: { scheme: flat, threshold_pct: 30 }",
        "rollup: { scheme: binned, thresholds: [10, 30] }"))
    # 2 equal-width bins over frequencies [6, 1, 0]: family(0) and career(1) fall in the rare
    # band -> bar 10%; education(6) in the common band -> bar 30%. So alpha's career (25% of
    # clips) now clears its 10% bar while education still needs (and clears) 30%.
    wide = run_topics_rollup(project).set_index("interview_key")
    assert wide.loc["fake_alpha", "topics"] == "education|career"
    assert wide.loc["fake_alpha", "n_topics"] == 2
    assert wide.loc["fake_beta", "topics"] == "education"
    _, long_p = interview_paths(project)
    long = pd.read_parquet(long_p)
    career = long[(long["interview_key"] == "fake_alpha") & (long["topic_id"] == "career")].iloc[0]
    assert career["threshold_pct"] == 10.0 and career["tagged"]
    edu = long[long["topic_id"] == "education"].iloc[0]
    assert edu["threshold_pct"] == 30.0


def test_rollup_schemas(project):
    write_hand_wide(project)
    run_topics_rollup(project)
    wide_p, long_p = interview_paths(project)
    assert list(pd.read_parquet(wide_p).columns) == [
        "interview_key", "n_sessions", "n_clips", "education", "career", "family",
        "topics", "n_topics"]
    assert list(pd.read_parquet(long_p).columns) == [
        "interview_key", "topic_id", "topic_name", "n_clips_assigned", "n_clips_total",
        "pct_clips", "threshold_pct", "tagged"]


def test_rollup_without_tag_fails(project):
    with pytest.raises(ToolkitError, match="topics tag"):
        run_topics_rollup(project)


# --- thresholds aid + annotate -------------------------------------------------------------


def test_thresholds_aid_prints_sweep_and_writes_figure(project, capsys):
    write_hand_wide(project)
    run_topics_thresholds(project)
    out = capsys.readouterr().out
    assert "Flat-threshold sweep" in out and ">= 10%" in out and ">= 40%" in out
    assert (project.diags_dir / "topics" / "plots" / "main_thresholds.png").exists()


def test_annotate_writes_per_interview_md(project):
    run_topics_tag(project, demo=True)
    run_topics_tag(project, yes=True)
    annotate_topics(project)
    for iid in sorted(project.clips["interview_id"].unique()):
        md = project.diags_dir / "topics" / f"main_{iid}.md"
        assert md.exists()
        text = md.read_text()
        assert "Clip 1" in text and "Education" in text


def test_annotate_without_deliverable_fails(project):
    with pytest.raises(ToolkitError, match="topics tag"):
        annotate_topics(project)
