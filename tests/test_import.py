import shutil
from pathlib import Path

import pandas as pd
import pytest
from docx import Document

from transcript_toolkit.errors import ToolkitError
from transcript_toolkit.project import init_project
from transcript_toolkit.steps.import_ import run_import, timestamp_regimes

FIXTURES = Path(__file__).parent / "fixtures"


def make_docx(project, name: str, lines: list[str]) -> None:
    doc = Document()
    for line in lines:
        doc.add_paragraph(line)
    doc.save(project.data_dir / name)


PER_PARAGRAPH = [                                   # every paragraph carries its own [HH:MM:SS]
    "[00:00:05] Q: Where did you grow up?",
    "[00:00:12] Delta: In a small town by the sea.",
    "[00:01:04] My father was a fisherman and my mother taught school.",
    "[00:02:20] Q: And what came after school?",
    "[00:02:30] Delta: University, then a long detour into journalism.",
]
PER_TURN_ONLY = [                                   # timestamp only on each speaker turn
    "[00:00:05] Q: Where did you grow up?",
    "[00:00:12] Echo: In a small town by the sea.",
    "My father was a fisherman and my mother taught school.",
    "That shaped how I saw the world for a long time afterwards.",
    "[00:02:20] Q: And what came after school?",
    "[00:02:30] Echo: University, then a long detour into journalism.",
]
FIXTURE_DOCX = [
    "Fake_Alpha_20240101_session1_SYNC.docx",
    "Fake_Alpha_20240108_session2_SYNC.docx",
    "Fake, Beta_SYNC.docx",
]


@pytest.fixture
def project(tmp_path):
    project = init_project(str(tmp_path / "ws"))
    for name in FIXTURE_DOCX:
        shutil.copy(FIXTURES / name, project.data_dir / name)
    return project


def test_import_end_to_end(project, capsys):
    df = run_import(project)
    assert project.paragraphs_path.exists()
    assert project.paragraphs_path.with_suffix(".csv").exists()
    assert set(df["interview_id"]) == {
        "fake_alpha_20240101_session1", "fake_alpha_20240108_session2", "fake_beta"}
    on_disk = pd.read_parquet(project.paragraphs_path)
    assert len(on_disk) == len(df) == 13 + 7 + 9 - 1   # docx paragraphs minus the orphan
    log = (project.logs_dir / "import_warnings.log").read_text()
    assert "before the first speaker turn" in log      # the orphan section
    assert "kept with the current speaker" in log      # the benign colon-note section
    out = capsys.readouterr().out
    assert "3 transcripts" in out
    assert "fake_alpha" in out and "session1" in out   # narrator-pooling table printed


def test_all_per_paragraph_no_timestamp_warning(project, capsys):
    make_docx(project, "Fake_Delta_SYNC.docx", PER_PARAGRAPH)
    # remove the mixed fixtures so only the clean transcript is present
    for f in project.data_dir.glob("Fake_Alpha*"):
        f.unlink()
    (project.data_dir / "Fake, Beta_SYNC.docx").unlink()
    df = run_import(project)
    assert all(r["ok"] for r in timestamp_regimes(df))
    out = capsys.readouterr().out
    assert "every paragraph carries its own" in out
    assert "⚠ Timestamps" not in out


def test_per_turn_only_transcript_warns(project, capsys):
    make_docx(project, "Fake_Echo_SYNC.docx", PER_TURN_ONLY)
    for f in project.data_dir.glob("Fake_Alpha*"):
        f.unlink()
    (project.data_dir / "Fake, Beta_SYNC.docx").unlink()
    df = run_import(project)
    echo = next(r for r in timestamp_regimes(df) if r["interview_id"] == "fake_echo")
    assert echo["coverage"] == 0.0 and echo["n_cont"] == 2 and not echo["ok"]
    out = capsys.readouterr().out
    assert "⚠ Timestamps" in out
    assert "speaker turns only" in out
    assert "fake_echo" in out


def test_import_is_idempotent(project):
    df1 = run_import(project)
    df2 = run_import(project)
    pd.testing.assert_frame_equal(df1, df2)


def test_duplicate_ids_abort(project):
    # same interview id from a second filename ("Fake, Beta" vs "Fake_Beta" + other suffix)
    shutil.copy(FIXTURES / "Fake, Beta_SYNC.docx", project.data_dir / "Fake_Beta_final.docx")
    with pytest.raises(ToolkitError, match="same interview id"):
        run_import(project)


def test_timestampless_docx_aborts_with_hint(project):
    doc = Document()
    doc.add_paragraph("Q: This transcript has no timestamps at all.")
    doc.add_paragraph("Gamma: So the parser must reject it loudly.")
    doc.save(project.data_dir / "Fake_Gamma_SYNC.docx")
    with pytest.raises(ToolkitError, match=r"Fake_Gamma_SYNC\.docx"):
        run_import(project)


def test_no_docx_aborts(tmp_path):
    project = init_project(str(tmp_path / "empty-ws"))
    with pytest.raises(ToolkitError, match="No .docx transcripts"):
        run_import(project)


def test_word_lock_files_ignored(project):
    shutil.copy(FIXTURES / "Fake, Beta_SYNC.docx", project.data_dir / "~$ke, Beta_SYNC.docx")
    df = run_import(project)
    assert set(df["interview_id"]) == {
        "fake_alpha_20240101_session1", "fake_alpha_20240108_session2", "fake_beta"}
