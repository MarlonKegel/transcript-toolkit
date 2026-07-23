import re
import shutil
from pathlib import Path

import pandas as pd
import pytest

import transcript_toolkit.steps.clip.run as clip_run
from transcript_toolkit.core.sampling import draw_interview_sample
from transcript_toolkit.errors import ToolkitError
from transcript_toolkit.project import init_project
from transcript_toolkit.state import load_state
from transcript_toolkit.steps.clip import annotate_clips, run_clip
from transcript_toolkit.steps.clip.chunking import Chunk
from transcript_toolkit.steps.clip.run import ChunkSegmentation, Clip, stitch_chunks
from transcript_toolkit.steps.import_ import run_import

FIXTURES = Path(__file__).parent / "fixtures"

USAGE = {"input_tokens": 2000, "output_tokens": 80, "reasoning_tokens": 20, "cached_input_tokens": 500}

PARA_LINE_RE = re.compile(r"^\[(\d+)\] ", re.M)


def decision_region_idxs(user_content: str) -> list[int]:
    """Paragraph idxs the model must decide on: everything after the standalone
    DECISION REGION STARTS marker line (chunks >= 1), else all paragraph lines."""
    marker = "\nDECISION REGION STARTS\n"
    tail = user_content.split(marker, 1)[1] if marker in user_content else user_content
    return [int(m.group(1)) for m in PARA_LINE_RE.finditer(tail)]


def segmentation_for(idxs: list[int], drop_last: bool = False) -> dict:
    """Deterministic, schema-valid segmentation: the decision region split into two clips
    (one if too small). drop_last leaves the final paragraph uncovered (validation failure)."""
    lo, hi = idxs[0], idxs[-1]
    if drop_last:
        hi -= 1
    if hi - lo >= 1:
        mid = (lo + hi) // 2
        clips = [{"start_paragraph_idx": lo, "end_paragraph_idx": mid},
                 {"start_paragraph_idx": mid + 1, "end_paragraph_idx": hi}]
    else:
        clips = [{"start_paragraph_idx": lo, "end_paragraph_idx": hi}]
    return {"clips": clips, "procedural_paragraph_idxs": []}


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
        calls.append((instructions, user_content))
        return segmentation_for(decision_region_idxs(user_content)), USAGE

    monkeypatch.setattr(clip_run, "call_llm", fake_call_llm)
    monkeypatch.setattr(clip_run, "openai_client", lambda root: object())
    project.llm_calls = calls  # test-only attribute
    return project


SAMPLE = ["fake_alpha_20240101_session1", "fake_beta"]


def draw_sample(project):
    return draw_interview_sample(project, explicit=SAMPLE)


def out_clips(project):
    return project.outputs_dir / "clips" / "clips.parquet"


def out_paras(project):
    return project.outputs_dir / "clips" / "paragraphs_clipped.parquet"


# --- demo / gate ------------------------------------------------------------------------------

def test_demo_requires_sample(project):
    with pytest.raises(ToolkitError, match="No demo sample"):
        run_clip(project, demo=True)


def test_demo_writes_mds_only_and_records_state(project):
    draw_sample(project)
    df = run_clip(project, demo=True)
    assert sorted(df["interview_id"].unique()) == SAMPLE
    assert not out_clips(project).exists()                # no deliverable from a demo
    for iid in SAMPLE:
        md = project.diags_dir / "clip" / f"{iid}.md"
        assert md.exists() and "## Clip 1 —" in md.read_text()
    assert not (project.diags_dir / "clip" / "fake_alpha_20240108_session2.md").exists()
    demo = load_state(project)["steps"]["clip"]["demo"]
    assert demo["units"] == SAMPLE
    assert (project.cache_dir / "clip.jsonl").exists()


def test_full_run_gated_without_demo(project):
    with pytest.raises(ToolkitError, match="No demo run"):
        run_clip(project, yes=True)


def test_prompt_edit_stales_demo(project):
    draw_sample(project)
    run_clip(project, demo=True)
    prompt = project.prompts_dir / "segment_interview.md"
    prompt.write_text(prompt.read_text() + "\nNever split anecdotes.")
    with pytest.raises(ToolkitError, match="stale"):
        run_clip(project, yes=True)


def test_threshold_edit_stales_demo(project):
    draw_sample(project)
    run_clip(project, demo=True)
    adv = project.advanced_dir / "clip.yaml"
    adv.write_text(adv.read_text().replace("chunk_threshold_tokens: 20000",
                                           "chunk_threshold_tokens: 19000"))
    with pytest.raises(ToolkitError, match="stale"):
        run_clip(project, yes=True)


# --- full run / deliverables --------------------------------------------------------------------

def test_full_run_after_demo_reuses_cache(project):
    draw_sample(project)
    run_clip(project, demo=True)
    n_demo_calls = len(project.llm_calls)
    assert n_demo_calls == 2                              # one single-chunk call per sample interview
    df = run_clip(project, yes=True)
    assert len(project.llm_calls) == n_demo_calls + 1     # only the third interview was fresh
    assert out_clips(project).exists() and out_paras(project).exists()
    assert sorted(df["interview_id"].unique()) == SAMPLE[:1] + ["fake_alpha_20240108_session2", "fake_beta"]
    assert set(df.columns) == {"interview_id", "clip_id", "start_paragraph_idx", "end_paragraph_idx",
                               "n_paragraphs", "total_words", "start_ts", "end_ts",
                               "duration_seconds", "model", "reasoning_effort"}
    assert df["clip_id"].iloc[0] == df["interview_id"].iloc[0] + "_0001"
    full = load_state(project)["steps"]["clip"]["full"]
    assert full["n_units"] == 3
    # Every paragraph landed in a clip (fake never marks procedural); csv siblings written.
    paras = pd.read_parquet(out_paras(project))
    assert paras["clip_id"].notna().all()
    assert out_clips(project).with_suffix(".csv").exists()


def test_skip_demo_check_bypasses_gate(project):
    df = run_clip(project, yes=True, skip_demo_check=True)
    assert out_clips(project).exists() and len(df) > 0


def test_subset_merge_not_clobbering(project):
    draw_sample(project)
    run_clip(project, demo=True)
    run_clip(project, yes=True)
    before = pd.read_parquet(out_clips(project))
    run_clip(project, interviews=["fake_beta"], yes=True)
    after = pd.read_parquet(out_clips(project))
    assert sorted(after["interview_id"].unique()) == sorted(before["interview_id"].unique())
    assert len(after) == len(before)
    paras_after = pd.read_parquet(out_paras(project))
    assert sorted(paras_after["interview_id"].unique()) == sorted(before["interview_id"].unique())
    # No full-run record for a subset run beyond the original one.
    assert load_state(project)["steps"]["clip"]["full"]["n_units"] == 3


def test_unknown_interview_fails_loud(project):
    run_import(project)
    with pytest.raises(ToolkitError, match="Unknown interview id"):
        run_clip(project, interviews=["nobody"], yes=True, skip_demo_check=True)


# --- chunked path ---------------------------------------------------------------------------------

def test_multichunk_locked_context_and_stitching(project):
    adv = project.advanced_dir / "clip.yaml"
    text = adv.read_text().replace("chunk_threshold_tokens: 20000", "chunk_threshold_tokens: 600")
    adv.write_text(text.replace("overlap_paragraphs: 20", "overlap_paragraphs: 4"))
    draw_interview_sample(project, explicit=["fake_beta"])
    df = run_clip(project, demo=True)

    assert len(project.llm_calls) >= 2                    # beta split into several chunks
    chunked = [uc for _, uc in project.llm_calls
               if "## Continuing context from the previous chunk" in uc]
    assert chunked, "no chunk carried the locked-context preamble"
    assert all("\nDECISION REGION STARTS\n" in uc for uc in chunked)
    assert any("[LOCKED]" in uc for uc in chunked)
    # One cache record per (interview, chunk).
    import json
    records = [json.loads(line) for line in (project.cache_dir / "clip.jsonl").read_text().splitlines()]
    assert [r["chunk_idx"] for r in records] == list(range(len(records)))
    # Stitched clips partition the interview's paragraphs contiguously.
    clips = df.sort_values("start_paragraph_idx")
    assert int(clips["start_paragraph_idx"].iloc[0]) == 0
    starts = clips["start_paragraph_idx"].tolist()
    ends = clips["end_paragraph_idx"].tolist()
    assert all(s == e + 1 for s, e in zip(starts[1:], ends[:-1]))
    assert int(ends[-1]) == 8                             # fake_beta has 9 paragraphs


# --- validation failure ------------------------------------------------------------------------

def test_coverage_failure_fails_interview_loudly(project, monkeypatch):
    def bad_call_llm(client, model, reasoning, verbosity, schema, instructions,
                     user_content, prompt_cache_key_str, **kwargs):
        return segmentation_for(decision_region_idxs(user_content), drop_last=True), USAGE

    monkeypatch.setattr(clip_run, "call_llm", bad_call_llm)
    draw_sample(project)
    with pytest.raises(ToolkitError, match="failed clip validation"):
        run_clip(project, demo=True)
    assert (project.logs_dir / "clip_validation.log").exists()
    assert "Missing paragraph indices" in (project.logs_dir / "clip_validation.log").read_text()
    assert "demo" not in load_state(project)["steps"].get("clip", {})
    assert not out_clips(project).exists()


def test_partial_failure_writes_successes_and_raises(project, monkeypatch):
    def flaky_call_llm(client, model, reasoning, verbosity, schema, instructions,
                       user_content, prompt_cache_key_str, **kwargs):
        idxs = decision_region_idxs(user_content)
        return segmentation_for(idxs, drop_last="dams" in user_content), USAGE

    monkeypatch.setattr(clip_run, "call_llm", flaky_call_llm)   # fake_beta fails
    with pytest.raises(ToolkitError, match="fake_beta"):
        run_clip(project, yes=True, skip_demo_check=True)
    written = pd.read_parquet(out_clips(project))
    assert sorted(written["interview_id"].unique()) == ["fake_alpha_20240101_session1",
                                                        "fake_alpha_20240108_session2"]
    assert "full" not in load_state(project)["steps"].get("clip", {})   # incomplete run never recorded


# --- stitching units -----------------------------------------------------------------------------

def seg(clips: list[tuple[int, int]], procedural: list[int] = ()) -> ChunkSegmentation:
    return ChunkSegmentation(
        clips=[Clip(start_paragraph_idx=s, end_paragraph_idx=e) for s, e in clips],
        procedural_paragraph_idxs=list(procedural))


def test_stitch_truncates_and_extends_locked_clip():
    c0 = Chunk(chunk_idx=0, shown_start=0, shown_end=11, decision_start=0,
               owned_start=0, owned_end=9, est_tokens=0)
    c1 = Chunk(chunk_idx=1, shown_start=8, shown_end=19, decision_start=10,
               owned_start=10, owned_end=19, est_tokens=0)
    # Chunk 0's second clip straddles its owned end (truncated to 9); chunk 1 extends it to 13.
    clips, procedural = stitch_chunks([
        (c0, seg([(0, 5), (6, 11)])),
        (c1, seg([(6, 13), (14, 19)])),
    ])
    assert [(c.start_paragraph_idx, c.end_paragraph_idx) for c in clips] == [(0, 5), (6, 13), (14, 19)]
    assert procedural == []


def test_stitch_extension_mismatch_fails():
    c0 = Chunk(chunk_idx=0, shown_start=0, shown_end=11, decision_start=0,
               owned_start=0, owned_end=9, est_tokens=0)
    c1 = Chunk(chunk_idx=1, shown_start=8, shown_end=19, decision_start=10,
               owned_start=10, owned_end=19, est_tokens=0)
    with pytest.raises(RuntimeError, match="neither the previous final clip"):
        stitch_chunks([
            (c0, seg([(0, 5), (6, 11)])),
            (c1, seg([(7, 13), (14, 19)])),               # 7 is neither prev.start (6) nor shown_start (8)
        ])


def test_stitch_extension_anchored_at_shown_start():
    # Regression (the kramer_larry failure): the seam clip's TRUE start is before this chunk's
    # shown_start, so the model can only see it from shown_start and anchors the extension there.
    # Geometry mirrors the real failure: prev clip (116,126), chunk-1 shown_start=117.
    c0 = Chunk(chunk_idx=0, shown_start=0, shown_end=136, decision_start=0,
               owned_start=0, owned_end=126, est_tokens=0)
    c1 = Chunk(chunk_idx=1, shown_start=117, shown_end=287, decision_start=127,
               owned_start=127, owned_end=277, est_tokens=0)
    clips, _ = stitch_chunks([
        (c0, seg([(100, 115), (116, 126)])),              # last clip truly starts at 116
        (c1, seg([(117, 141), (142, 150)])),              # extension anchored at shown_start=117
    ])
    # merged clip keeps the TRUE start 116 and takes the extended end 141
    assert [(c.start_paragraph_idx, c.end_paragraph_idx) for c in clips] == [
        (100, 115), (116, 141), (142, 150)]


def test_stitch_shown_start_extension_requires_clip_to_span_it():
    # shown_start anchoring is only valid when the previous clip actually spans shown_start.
    # Here the previous clip (6,7) ends before shown_start=8, so an ext at 8 is a real error.
    c0 = Chunk(chunk_idx=0, shown_start=0, shown_end=11, decision_start=0,
               owned_start=0, owned_end=9, est_tokens=0)
    c1 = Chunk(chunk_idx=1, shown_start=8, shown_end=19, decision_start=10,
               owned_start=10, owned_end=19, est_tokens=0)
    with pytest.raises(RuntimeError, match="neither the previous final clip"):
        stitch_chunks([
            (c0, seg([(0, 5), (6, 7)], procedural=[8, 9])),
            (c1, seg([(8, 13), (14, 19)])),
        ])


def test_stitch_discards_throwaway_and_restricts_procedural():
    c0 = Chunk(chunk_idx=0, shown_start=0, shown_end=11, decision_start=0,
               owned_start=0, owned_end=9, est_tokens=0)
    c1 = Chunk(chunk_idx=1, shown_start=8, shown_end=19, decision_start=10,
               owned_start=10, owned_end=19, est_tokens=0)
    clips, procedural = stitch_chunks([
        (c0, seg([(0, 4), (6, 9), (10, 11)], procedural=[5, 10])),   # (10,11) + proc 10: throwaway
        (c1, seg([(10, 19)], procedural=[])),
    ])
    assert [(c.start_paragraph_idx, c.end_paragraph_idx) for c in clips] == [(0, 4), (6, 9), (10, 19)]
    assert procedural == [5]                              # 10 was outside chunk 0's owned region


# --- annotate ------------------------------------------------------------------------------------

def test_annotate_rerenders_from_deliverable(project):
    run_clip(project, yes=True, skip_demo_check=True)
    md = project.diags_dir / "clip" / "fake_beta.md"
    md.unlink()
    annotate_clips(project)
    assert md.exists() and "# fake_beta" in md.read_text()


def test_annotate_without_deliverable_fails(project):
    with pytest.raises(ToolkitError, match="Run `toolkit clip` first"):
        annotate_clips(project)
