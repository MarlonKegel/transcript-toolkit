import re
import shutil
from pathlib import Path

import pandas as pd
import pytest

import transcript_toolkit.steps.clip.run as clip_run
import transcript_toolkit.steps.label.run as label_run
from transcript_toolkit.core.sampling import draw_interview_sample
from transcript_toolkit.errors import ToolkitError
from transcript_toolkit.project import init_project
from transcript_toolkit.state import load_state
from transcript_toolkit.steps.import_ import run_import
from transcript_toolkit.steps.label import annotate_labels, run_label
from transcript_toolkit.steps.label.batching import batch_clips

FIXTURES = Path(__file__).parent / "fixtures"

USAGE = {"input_tokens": 1500, "output_tokens": 60, "reasoning_tokens": 15, "cached_input_tokens": 400}

PARA_LINE_RE = re.compile(r"^\[(\d+)\] ", re.M)
CLIP_HDR_RE = re.compile(r"^## CLIP (\d+)$")


def fake_clip_llm(client, model, reasoning, verbosity, schema, instructions,
                  user_content, prompt_cache_key_str, **kwargs):
    """Single-chunk segmentation: split the interview's paragraphs into two clips."""
    idxs = [int(m.group(1)) for m in PARA_LINE_RE.finditer(user_content)]
    lo, hi = idxs[0], idxs[-1]
    mid = (lo + hi) // 2
    return {"clips": [{"start_paragraph_idx": lo, "end_paragraph_idx": mid},
                      {"start_paragraph_idx": mid + 1, "end_paragraph_idx": hi}],
            "procedural_paragraph_idxs": []}, USAGE


def labels_for(user_content: str) -> list[dict]:
    """One deterministic label per `## CLIP n` section, encoding the section's first
    paragraph idx so tests can verify batch-local numbers map back to the right clips."""
    labels = []
    current = None
    for line in user_content.splitlines():
        m = CLIP_HDR_RE.match(line)
        if m:
            current = int(m.group(1))
            continue
        p = PARA_LINE_RE.match(line)
        if p and current is not None:
            labels.append({"clip_number": current,
                           "label": f"Clip starting at {p.group(1)} (local {current})"})
            current = None
    return labels


@pytest.fixture
def project(tmp_path, monkeypatch):
    project = init_project(str(tmp_path / "ws"))
    for name in ["Fake_Alpha_20240101_session1_SYNC.docx",
                 "Fake_Alpha_20240108_session2_SYNC.docx",
                 "Fake, Beta_SYNC.docx"]:
        shutil.copy(FIXTURES / name, project.data_dir / name)
    run_import(project)

    # Produce the clip deliverables the label step consumes (two clips per interview).
    monkeypatch.setattr(clip_run, "call_llm", fake_clip_llm)
    monkeypatch.setattr(clip_run, "openai_client", lambda root: object())
    clip_run.run_clip(project, yes=True, skip_demo_check=True)

    calls = []

    def fake_label_llm(client, model, reasoning, verbosity, schema, instructions,
                       user_content, prompt_cache_key_str, **kwargs):
        calls.append((instructions, user_content))
        return {"labels": labels_for(user_content)}, USAGE

    monkeypatch.setattr(label_run, "call_llm", fake_label_llm)
    monkeypatch.setattr(label_run, "openai_client", lambda root: object())
    project.llm_calls = calls  # test-only attribute
    return project


SAMPLE = ["fake_alpha_20240101_session1", "fake_beta"]


def draw_sample(project):
    return draw_interview_sample(project, explicit=SAMPLE)


def out_path(project):
    return project.outputs_dir / "labels" / "labels.parquet"


# --- batching unit -------------------------------------------------------------------------------

def test_batch_clips_threshold_partition_and_neighbors():
    tokens = {"a": 40, "b": 40, "c": 40, "d": 90}
    batches = batch_clips("iv", ["a", "b", "c", "d"], tokens, 100)
    assert [b.clip_ids for b in batches] == [["a", "b"], ["c"], ["d"]]
    assert [b.batch_idx for b in batches] == [0, 1, 2]
    assert [b.est_tokens for b in batches] == [80, 40, 90]
    assert all(b.est_tokens <= 100 for b in batches)
    assert [(b.prev_clip_id, b.next_clip_id) for b in batches] == [
        (None, "c"), ("b", "d"), ("c", None)]
    # A single clip over budget still becomes its own batch.
    (big,) = batch_clips("iv", ["x"], {"x": 500}, 100)
    assert big.clip_ids == ["x"] and big.est_tokens == 500


# --- demo / gate ------------------------------------------------------------------------------

def test_demo_requires_sample(project):
    with pytest.raises(ToolkitError, match="No demo sample"):
        run_label(project, demo=True)


def test_demo_writes_mds_only_and_records_state(project):
    draw_sample(project)
    df = run_label(project, demo=True)
    assert sorted(df["interview_id"].unique()) == SAMPLE
    assert not out_path(project).exists()
    for iid in SAMPLE:
        page = project.diags_dir / "label" / f"{iid}.html"
        assert page.exists() and "Label:</span> Clip starting at" in page.read_text()
    assert (project.diags_dir / "label" / "index.html").exists()
    demo = load_state(project)["steps"]["label"]["demo"]
    assert demo["units"] == SAMPLE
    assert (project.cache_dir / "label.jsonl").exists()


def test_full_run_gated_without_demo(project):
    with pytest.raises(ToolkitError, match="No demo run"):
        run_label(project, yes=True)


def test_prompt_edit_stales_demo(project):
    draw_sample(project)
    run_label(project, demo=True)
    prompt = project.prompts_dir / "label_clips.md"
    prompt.write_text(prompt.read_text() + "\nNever use gerunds.")
    with pytest.raises(ToolkitError, match="stale"):
        run_label(project, yes=True)


# --- full run / deliverable ----------------------------------------------------------------------

def test_full_run_after_demo_reuses_cache(project):
    draw_sample(project)
    run_label(project, demo=True)
    n_demo_calls = len(project.llm_calls)
    assert n_demo_calls == 2                              # one batch per sample interview (default threshold)
    df = run_label(project, yes=True)
    assert len(project.llm_calls) == n_demo_calls + 1     # only the third interview was fresh
    assert out_path(project).exists() and out_path(project).with_suffix(".csv").exists()
    assert len(df) == 6                                   # 3 interviews x 2 clips
    clips_cols = {"interview_id", "clip_id", "start_paragraph_idx", "end_paragraph_idx",
                  "n_paragraphs", "total_words", "start_ts", "end_ts", "duration_seconds"}
    assert set(df.columns) == clips_cols | {"label", "batch_idx", "model", "reasoning_effort"}
    assert (df["model"] == "gpt-5.4").all()               # the LABEL model, not the clip model
    # Batch-local clip numbers mapped back to the right global clips.
    for r in df.itertuples():
        assert r.label.startswith(f"Clip starting at {r.start_paragraph_idx} ")
    assert load_state(project)["steps"]["label"]["full"]["n_units"] == 3


def test_subset_merge_not_clobbering(project):
    draw_sample(project)
    run_label(project, demo=True)
    run_label(project, yes=True)
    before = pd.read_parquet(out_path(project))
    run_label(project, interviews=["fake_beta"], yes=True)
    after = pd.read_parquet(out_path(project))
    assert len(after) == len(before) == 6
    assert sorted(after["interview_id"].unique()) == sorted(before["interview_id"].unique())


def test_unknown_interview_fails_loud(project):
    with pytest.raises(ToolkitError, match="Unknown interview id"):
        run_label(project, interviews=["nobody"], yes=True, skip_demo_check=True)


# --- batching through the run --------------------------------------------------------------------

def test_small_threshold_batches_with_neighbor_context(project):
    adv = project.advanced_dir / "label.yaml"
    adv.write_text(adv.read_text().replace("batch_threshold_tokens: 10000",
                                           "batch_threshold_tokens: 50"))
    draw_interview_sample(project, explicit=["fake_beta"])
    df = run_label(project, demo=True)

    assert len(project.llm_calls) == 2                    # each of beta's 2 clips its own batch
    first, second = [uc for _, uc in project.llm_calls]
    assert "## PREVIOUS CLIP (context only — do NOT label)" not in first
    assert "## NEXT CLIP (context only — do NOT label)" in first
    assert "## PREVIOUS CLIP (context only — do NOT label)" in second
    assert "## NEXT CLIP (context only — do NOT label)" not in second
    # Batch-local numbering: each single-clip batch labels its clip as CLIP 1 ...
    assert first.count("## CLIP 1\n") == 1 and second.count("## CLIP 1\n") == 1
    assert "## CLIP 2" not in first and "## CLIP 2" not in second
    # ... and the deliverable rows still map to the right global clips and batches.
    df = df.sort_values("start_paragraph_idx")
    assert df["batch_idx"].tolist() == [0, 1]
    for r in df.itertuples():
        assert r.label.startswith(f"Clip starting at {r.start_paragraph_idx} ")


# --- hard validation ------------------------------------------------------------------------------

def test_bad_count_fails_interview_loudly(project, monkeypatch):
    def bad_label_llm(client, model, reasoning, verbosity, schema, instructions,
                      user_content, prompt_cache_key_str, **kwargs):
        labels = labels_for(user_content)
        labels.append({"clip_number": len(labels) + 1, "label": "phantom clip"})
        return {"labels": labels}, USAGE

    monkeypatch.setattr(label_run, "call_llm", bad_label_llm)
    draw_sample(project)
    with pytest.raises(ToolkitError, match="failed label validation"):
        run_label(project, demo=True)
    log = project.logs_dir / "label_validation.log"
    assert log.exists() and "expected" in log.read_text()
    assert "demo" not in load_state(project)["steps"].get("label", {})
    assert not out_path(project).exists()


def test_empty_label_fails_interview(project, monkeypatch):
    def empty_label_llm(client, model, reasoning, verbosity, schema, instructions,
                        user_content, prompt_cache_key_str, **kwargs):
        labels = labels_for(user_content)
        labels[0]["label"] = "   "
        return {"labels": labels}, USAGE

    monkeypatch.setattr(label_run, "call_llm", empty_label_llm)
    with pytest.raises(ToolkitError, match="failed label validation"):
        run_label(project, yes=True, skip_demo_check=True)
    assert not out_path(project).exists()                 # every interview failed -> nothing written


def test_partial_failure_writes_successes_and_raises(project, monkeypatch):
    def flaky_label_llm(client, model, reasoning, verbosity, schema, instructions,
                        user_content, prompt_cache_key_str, **kwargs):
        labels = labels_for(user_content)
        if "dams" in user_content:                        # only fake_beta's batch
            labels = labels[:-1]
        return {"labels": labels}, USAGE

    monkeypatch.setattr(label_run, "call_llm", flaky_label_llm)
    with pytest.raises(ToolkitError, match="fake_beta"):
        run_label(project, yes=True, skip_demo_check=True)
    written = pd.read_parquet(out_path(project))
    assert sorted(written["interview_id"].unique()) == ["fake_alpha_20240101_session1",
                                                        "fake_alpha_20240108_session2"]
    assert "full" not in load_state(project)["steps"].get("label", {})


# --- addendum -------------------------------------------------------------------------------------

def enable_addendum(project):
    cfg = project.config_path
    cfg.write_text(cfg.read_text().replace("addendum: null", "addendum: prompts/label_addendum.md"))


def test_addendum_appended_to_instructions(project):
    enable_addendum(project)
    (project.prompts_dir / "label_addendum.md").write_text("Always write OSF, never Open Society Foundations.\n")
    draw_sample(project)
    run_label(project, demo=True)
    instructions = project.llm_calls[0][0]
    assert instructions.endswith("\n\n## Project-specific consistency rules\n\n"
                                 "Always write OSF, never Open Society Foundations.")


def test_addendum_missing_file_fails_loud(project):
    enable_addendum(project)
    with pytest.raises(ToolkitError, match="addendum not found"):
        run_label(project, demo=True)


def test_addendum_edit_stales_demo(project):
    draw_sample(project)
    run_label(project, demo=True)                         # demo without addendum
    enable_addendum(project)
    (project.prompts_dir / "label_addendum.md").write_text("Always write OSF.\n")
    with pytest.raises(ToolkitError, match="stale"):
        run_label(project, yes=True)


# --- annotate ------------------------------------------------------------------------------------

def test_annotate_rerenders_from_deliverable(project):
    run_label(project, yes=True, skip_demo_check=True)
    page = project.diags_dir / "label" / "fake_beta.html"
    page.unlink()
    annotate_labels(project)
    assert page.exists() and "Label:</span> Clip starting at" in page.read_text()


def test_annotate_without_deliverable_fails(project):
    with pytest.raises(ToolkitError, match="Run `toolkit label` first"):
        annotate_labels(project)


def test_batch_transport_fills_cache_and_builds_deliverable(project, monkeypatch):
    """--batch sends every uncached grouped call across all interviews in one Batch-API job;
    per-interview validation then runs against the cached results, with no synchronous call."""
    import json

    import transcript_toolkit.core.batch as batch_mod

    def fake_run_batch(client, units, batch_dir, **kwargs):
        return {u["custom_id"]: ({"labels": labels_for(u["user_content"])}, USAGE)
                for u in units}, []

    monkeypatch.setattr(batch_mod, "run_batch", fake_run_batch)
    monkeypatch.setattr(label_run, "call_llm",
                        lambda *a, **k: pytest.fail("batch run must not call the sync API"))

    df = run_label(project, yes=True, skip_demo_check=True, batch=True)
    assert len(df) == 6                                   # 3 interviews x 2 clips
    assert df["label"].str.startswith("Clip starting at").all()
    records = [json.loads(ln) for ln
               in (project.cache_dir / "label.jsonl").read_text().splitlines()]
    assert records and all(r.get("api") == "batch" for r in records)
    # custom_ids are per interview+group, so results map back to the right grouped call
    assert {r["interview_id"] for r in records} == set(df["interview_id"])
