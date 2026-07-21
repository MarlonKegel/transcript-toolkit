import shutil
from pathlib import Path

import pandas as pd
import pytest
from docx import Document

from transcript_toolkit.errors import ToolkitError
from transcript_toolkit.project import init_project
from transcript_toolkit.steps.import_ import run_import

FIXTURES = Path(__file__).parent / "fixtures"
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
    warnings = (project.logs_dir / "import_warnings.log").read_text().splitlines()
    assert len(warnings) == 2                          # 1 orphan + 1 stray mid-turn timestamp
    out = capsys.readouterr().out
    assert "3 transcripts" in out
    assert "fake_alpha" in out and "session1" in out   # narrator-pooling table printed


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
