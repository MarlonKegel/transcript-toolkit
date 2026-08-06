"""Re-importing a corrected transcript: the manifest, the purge, and the Imported column.

A transcript comes back corrected under the filename it always had. Import must replace the
old rows AND the results made from the old text, record when each file was read in, and say
all of it out loud — a spreadsheet is checked against a correction by these timestamps.
"""
import json
import re
import shutil
import time
from pathlib import Path

import pandas as pd
import pytest
from docx import Document

from transcript_toolkit.core import manifest
from transcript_toolkit.project import init_project
from transcript_toolkit.state import load_state, record_full
from transcript_toolkit.steps.import_ import run_import

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE_DOCX = [
    "Fake_Alpha_20240101_session1_SYNC.docx",
    "Fake_Alpha_20240108_session2_SYNC.docx",
    "Fake, Beta_SYNC.docx",
]
ALL_IDS = {"fake_alpha_20240101_session1", "fake_alpha_20240108_session2", "fake_beta"}

CORRECTED = [
    "[00:00:05] Q: Where did you grow up?",
    "[00:00:12] Beta: In a small town by the mountains.",     # the narrator's correction
]


@pytest.fixture
def project(tmp_path):
    project = init_project(str(tmp_path / "ws"))
    for name in FIXTURE_DOCX:
        shutil.copy(FIXTURES / name, project.data_dir / name)
    run_import(project)
    return project


def rewrite(project, name: str, lines: list[str]) -> None:
    doc = Document()
    for line in lines:
        doc.add_paragraph(line)
    doc.save(project.data_dir / name)


def fabricate_results(project) -> None:
    """Hand-made deliverables for two interviews, as if clip and summarize had run."""
    out = project.outputs_dir
    (out / "clips").mkdir(parents=True, exist_ok=True)
    clips = pd.DataFrame([
        {"clip_id": "fake_beta_0001", "interview_id": "fake_beta",
         "start_ts": "00:00:05", "end_ts": "00:01:00"},
        {"clip_id": "fake_alpha_20240101_session1_0001",
         "interview_id": "fake_alpha_20240101_session1",
         "start_ts": "00:00:05", "end_ts": "00:01:00"},
    ])
    clips.to_parquet(out / "clips" / "clips.parquet", index=False)
    clips.to_csv(out / "clips" / "clips.csv", index=False)
    (out / "summaries").mkdir(parents=True, exist_ok=True)
    pd.DataFrame([
        {"interview_key": "fake_beta", "session_ids": "fake_beta", "summary": "s", "synced": True},
        {"interview_key": "fake_alpha",
         "session_ids": "fake_alpha_20240101_session1|fake_alpha_20240108_session2",
         "summary": "s", "synced": True},
    ]).to_parquet(out / "summaries" / "summaries.parquet", index=False)
    record_full(project, "clip", "fp", model="m", n_units=2)


def test_import_records_when_each_transcript_came_in(project):
    stamps = manifest.imported_at(project)
    assert set(stamps) == ALL_IDS
    assert all(stamps.values())


def test_reimporting_unchanged_files_keeps_their_imported_at(project):
    """The timestamp means "when this text came in", not "when import last ran"."""
    state = json.loads(project.import_manifest_path.read_text())
    for entry in state["synced"].values():
        entry["imported_at"] = "2020-01-01T00:00:00+00:00"
    project.import_manifest_path.write_text(json.dumps(state))

    run_import(project)
    assert all(ts == "2020-01-01T00:00:00+00:00"
               for ts in manifest.imported_at(project).values())


def test_a_changed_transcript_takes_its_old_results_with_it(project, capsys):
    fabricate_results(project)
    rewrite(project, "Fake, Beta_SYNC.docx", CORRECTED)

    run_import(project)

    clips = pd.read_parquet(project.outputs_dir / "clips" / "clips.parquet")
    assert list(clips["interview_id"]) == ["fake_alpha_20240101_session1"]
    clips_csv = pd.read_csv(project.outputs_dir / "clips" / "clips.csv")
    assert list(clips_csv["interview_id"]) == ["fake_alpha_20240101_session1"]
    summaries = pd.read_parquet(project.outputs_dir / "summaries" / "summaries.parquet")
    assert list(summaries["interview_key"]) == ["fake_alpha"]

    # coverage shrank with the purge, so freshness reports work remaining rather than done
    assert load_state(project)["steps"]["clip"]["full"]["n_units"] == 1

    printed = capsys.readouterr().out
    assert "1 transcript(s) changed since they were last imported: fake_beta" in printed
    assert "Results made from the old text were removed" in printed


def test_a_removed_transcript_takes_its_results_with_it_too(project):
    fabricate_results(project)
    (project.data_dir / "Fake, Beta_SYNC.docx").unlink()

    run_import(project)

    assert set(manifest.imported_at(project)) == ALL_IDS - {"fake_beta"}
    clips = pd.read_parquet(project.outputs_dir / "clips" / "clips.parquet")
    assert "fake_beta" not in set(clips["interview_id"])


def test_export_shows_when_each_transcript_was_imported(project):
    from transcript_toolkit.steps.export import build_interviews_sheet

    (project.outputs_dir / "summaries").mkdir(parents=True, exist_ok=True)
    pd.DataFrame([
        {"interview_key": "fake_beta", "session_ids": "fake_beta", "summary": "s", "synced": True},
    ]).to_parquet(project.outputs_dir / "summaries" / "summaries.parquet", index=False)

    sheet = build_interviews_sheet(project, sets=[])
    row = sheet[sheet["Interview"] == "fake_beta"].iloc[0]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", row["Imported"])


def test_a_replaced_file_reads_as_changed_in_the_transcript_list(project):
    """The list (and the Import button behind `everything_imported`) must notice a replaced
    file — otherwise the corrected transcript sits there looking done and never gets read in."""
    from transcript_toolkit.app import workspaces

    rows = {r["filename"]: r for r in workspaces.transcript_rows(project)}
    assert all(r["imported"] for r in rows.values())
    assert workspaces.everything_imported(project)

    time.sleep(2.1)          # the staleness check trusts files older than the recorded second
    rewrite(project, "Fake, Beta_SYNC.docx", CORRECTED)

    rows = {r["filename"]: r for r in workspaces.transcript_rows(project)}
    beta = rows["Fake, Beta_SYNC.docx"]
    assert not beta["imported"] and beta["changed"]
    assert not workspaces.everything_imported(project)
