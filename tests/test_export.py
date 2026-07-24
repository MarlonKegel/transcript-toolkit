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


# --- location modes ------------------------------------------------------------------------------
# fake_beta_0001 is tagged directly with Czechia and with the region "The Balkans" (which the
# mapping expands to Serbia + Croatia), plus the place-tag Crimea. Place-tags count as direct
# evidence — they are tagged in their own right, not derived from a region.

def _locations(project):
    _write(project, "locations/clip_countries.parquet", pd.DataFrame([
        {"interview_id": "fake_beta", "clip_id": "fake_beta_0001", "start_paragraph_idx": 0,
         "countries": "Czechia", "regions": "The Balkans",
         "countries_from_regions": "Serbia|Croatia",
         "countries_final": "Czechia|Crimea|Serbia|Croatia", "n_countries_final": 4,
         "has_country": True}]))
    _write(project, "locations/clip_countries_long.parquet", pd.DataFrame([
        {"interview_id": "fake_beta", "clip_id": "fake_beta_0001", "country": "Czechia",
         "via": "direct"},
        {"interview_id": "fake_beta", "clip_id": "fake_beta_0001", "country": "Crimea",
         "via": "place"},
        {"interview_id": "fake_beta", "clip_id": "fake_beta_0001", "country": "Serbia",
         "via": "The Balkans"},
        {"interview_id": "fake_beta", "clip_id": "fake_beta_0001", "country": "Croatia",
         "via": "The Balkans"}]))
    _write(project, "locations/interview_locations_wide.parquet", pd.DataFrame([
        {"interview_key": "fake_beta", "n_sessions": 1, "n_clips": 1, "regions": "The Balkans",
         "n_regions": 1, "labels": "Czechia|Crimea|Serbia|Croatia", "n_labels": 4}]))
    _write(project, "locations/interview_locations_long.parquet", pd.DataFrame([
        {"interview_key": "fake_beta", "label": "Czechia", "via": "direct"},
        {"interview_key": "fake_beta", "label": "Crimea", "via": "place"},
        {"interview_key": "fake_beta", "label": "Serbia", "via": "The Balkans"},
        {"interview_key": "fake_beta", "label": "Croatia", "via": "The Balkans"}]))


def _clip_cell(sheets, column):
    header = sheets["Clips"][0]
    row = next(r for r in sheets["Clips"][1:] if r[0] == "fake_beta_0001")
    return row[header.index(column)]


def test_locations_mode_countries_only(project):
    _clips(project)
    _locations(project)
    run_export(project, locations="countries")
    sheets = _sheets(project.outputs_dir / "export.xlsx")
    assert _clip_cell(sheets, "Locations") == "Crimea, Czechia"   # direct + place, no region fan-out
    assert "Regions" not in sheets["Clips"][0]
    assert "Regions" not in sheets["Interviews"][0]
    assert "Regions" not in sheets["Categories"][0]


def test_locations_mode_countries_and_regions(project):
    _clips(project)
    _locations(project)
    run_export(project, locations="countries_and_regions")
    sheets = _sheets(project.outputs_dir / "export.xlsx")
    assert _clip_cell(sheets, "Locations") == "Crimea, Czechia"
    assert _clip_cell(sheets, "Regions") == "The Balkans"
    iv_header = sheets["Interviews"][0]
    iv_row = sheets["Interviews"][1]
    assert iv_row[iv_header.index("Locations")] == "Crimea, Czechia"
    assert iv_row[iv_header.index("Regions")] == "The Balkans"
    assert "Regions" in sheets["Categories"][0]                   # reference list is usable here


def test_locations_mode_countries_incl_regions(project):
    _clips(project)
    _locations(project)
    run_export(project, locations="countries_incl_regions")
    sheets = _sheets(project.outputs_dir / "export.xlsx")
    assert _clip_cell(sheets, "Locations") == "Czechia, Crimea, Serbia, Croatia"
    assert "Regions" not in sheets["Clips"][0]
    iv_header = sheets["Interviews"][0]
    assert iv_header.count("Regions") == 0
    assert sheets["Interviews"][1][iv_header.index("Locations")] == "Czechia, Crimea, Serbia, Croatia"


def test_categories_location_list_follows_mode(project):
    _clips(project)
    _locations(project)
    run_export(project, locations="countries")
    cats = _sheets(project.outputs_dir / "export.xlsx")["Categories"]
    col = [r[cats[0].index("Locations")] for r in cats[1:]]
    assert [c for c in col if c] == ["Crimea", "Czechia"]         # region-derived names excluded

    run_export(project, locations="countries_incl_regions")
    cats = _sheets(project.outputs_dir / "export.xlsx")["Categories"]
    col = [r[cats[0].index("Locations")] for r in cats[1:]]
    assert [c for c in col if c] == ["Crimea", "Croatia", "Czechia", "Serbia"]


def test_default_mode_from_config_and_bad_mode_fails_loud(project, capsys):
    _clips(project)
    _locations(project)
    run_export(project)                                            # scaffold default
    sheets = _sheets(project.outputs_dir / "export.xlsx")
    assert "Regions" in sheets["Clips"][0]                         # countries_and_regions
    assert "countries_and_regions" in capsys.readouterr().out

    cfg = project.config_path
    cfg.write_text(cfg.read_text().replace("locations: countries_and_regions",
                                           "locations: countries"))
    run_export(project)
    assert "Regions" not in _sheets(project.outputs_dir / "export.xlsx")["Clips"][0]

    cfg.write_text(cfg.read_text().replace("locations: countries", "locations: nonsense"))
    with pytest.raises(ToolkitError, match="export.locations must be one of"):
        run_export(project)


def test_no_dropdown_note(project, capsys):
    _clips(project)
    run_export(project)
    assert "multi-select" not in capsys.readouterr().out
