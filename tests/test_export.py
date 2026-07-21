import shutil
from pathlib import Path

import openpyxl
import pandas as pd
import pytest

from transcript_toolkit.errors import ToolkitError
from transcript_toolkit.project import init_project
from transcript_toolkit.steps.export import run_export
from transcript_toolkit.steps.import_ import run_import

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def project(tmp_path):
    project = init_project(str(tmp_path / "ws"))
    for name in ["Fake_Alpha_20240101_session1_SYNC.docx",
                 "Fake_Alpha_20240108_session2_SYNC.docx", "Fake, Beta_SYNC.docx"]:
        shutil.copy(FIXTURES / name, project.data_dir / name)
    run_import(project)
    return project


def _write(project, rel, df):
    path = project.outputs_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def _clips(project):
    _write(project, "clips/clips.parquet", pd.DataFrame([
        {"interview_id": "fake_beta", "clip_id": "fake_beta_0001", "start_paragraph_idx": 0,
         "end_paragraph_idx": 1, "n_paragraphs": 2, "total_words": 20, "start_ts": "00:00:06",
         "end_ts": "00:01:40", "duration_seconds": 94, "model": "m", "reasoning_effort": "r"},
        {"interview_id": "fake_alpha_20240101_session1", "clip_id": "fake_alpha_20240101_session1_0001",
         "start_paragraph_idx": 0, "end_paragraph_idx": 2, "n_paragraphs": 3, "total_words": 40,
         "start_ts": "00:00:20", "end_ts": "00:03:00", "duration_seconds": 160,
         "model": "m", "reasoning_effort": "r"},
    ]))


def _sheets(path):
    wb = openpyxl.load_workbook(path)
    return {ws.title: [[c.value for c in row] for row in ws.iter_rows()] for ws in wb.worksheets}


def test_export_needs_clips(project):
    with pytest.raises(ToolkitError, match="run `toolkit clip`"):
        run_export(project)


def test_export_clips_only(project):
    _clips(project)
    run_export(project)
    sheets = _sheets(project.outputs_dir / "export.xlsx")
    assert "Clips" in sheets and "Interviews" not in sheets   # nothing interview-level yet
    header = sheets["Clips"][0]
    assert header[:5] == ["Clip Id", "Interview", "Session", "Start", "End"]
    assert "Label" not in header                              # label step hasn't run
    body = sheets["Clips"][1:]
    beta = next(r for r in body if r[0] == "fake_beta_0001")
    assert beta[1] == "fake_beta" and beta[2] == "fake_beta"  # Interview / Session
    alpha = next(r for r in body if r[0].startswith("fake_alpha"))
    assert alpha[1] == "fake_alpha" and alpha[2] == "fake_alpha_20240101_session1"  # pooling


def test_export_incremental_adds_columns(project):
    _clips(project)
    _write(project, "labels/labels.parquet", pd.DataFrame([
        {"interview_id": "fake_beta", "clip_id": "fake_beta_0001", "start_paragraph_idx": 0,
         "end_paragraph_idx": 1, "n_paragraphs": 2, "total_words": 20, "start_ts": "00:00:06",
         "end_ts": "00:01:40", "duration_seconds": 94, "label": "on becoming a publisher",
         "batch_idx": 0, "model": "m", "reasoning_effort": "r"}]))
    _write(project, "summaries/summaries.parquet", pd.DataFrame([
        {"interview_key": "fake_beta", "session_ids": "fake_beta", "n_sessions": 1,
         "n_paragraphs": 5, "total_words": 100, "summary": "An abstract.", "summary_word_count": 2,
         "model": "m", "reasoning_effort": "r"}]))
    (project.topics_dir / "main.csv").write_text(
        "name,description\nEducation,About education.\nCareer and Work,About work.\n")
    _write(project, "topics/main_clip_topics_long.parquet", pd.DataFrame([
        {"clip_id": "fake_beta_0001", "interview_id": "fake_beta", "topic_id": "career",
         "topic_name": "Career and Work", "score": 2, "justification": ""},
        {"clip_id": "fake_beta_0001", "interview_id": "fake_beta", "topic_id": "education",
         "topic_name": "Education", "score": 1, "justification": ""}]))
    _write(project, "topics/main_interview_topics_wide.parquet", pd.DataFrame([
        {"interview_key": "fake_beta", "n_sessions": 1, "n_clips": 1, "topics": "Career and Work",
         "n_topics": 1}]))
    run_export(project)
    sheets = _sheets(project.outputs_dir / "export.xlsx")
    clips_header = sheets["Clips"][0]
    assert "Label" in clips_header and "Topics: main" in clips_header
    beta_row = next(r for r in sheets["Clips"][1:] if r[0] == "fake_beta_0001")
    # only the score-2 topic is tagged on the clip
    assert beta_row[clips_header.index("Topics: main")] == "Career and Work"
    assert "Interviews" in sheets
    assert sheets["Interviews"][0][:1] == ["Interview"]
    assert "Categories" in sheets
    cat_header = sheets["Categories"][0]
    assert "Topics: main" in cat_header                        # vocabulary from the topic list
