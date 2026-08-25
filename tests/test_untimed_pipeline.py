"""A transcript with no timestamps, all the way through.

The toolkit used to summarize these and stop, on the reasoning that a clip is a span between two
times. It is not: the model is given a numbered list of paragraphs and answers with paragraph
indices, and paragraph numbers are something every transcript has. So a transcript that was
never SYNC'd is clipped, labelled, tagged and exported like any other, and the only thing it
cannot show is when a clip starts and ends.

These tests run a mixed collection — two SYNC'd transcripts and one that never was — through
every step with the model stubbed out, and check the places where the difference actually
surfaces.
"""
import shutil
from pathlib import Path

import pandas as pd
import pytest

from transcript_toolkit.core import overrides as overrides_mod
from transcript_toolkit.core.tables import load_clips, untimed_ids
from transcript_toolkit.project import init_project
from transcript_toolkit.steps.import_ import run_import

FIXTURES = Path(__file__).parent / "fixtures"
UNTIMED_ID = "fake_gamma_transcript"


@pytest.fixture
def project(tmp_path):
    """A collection with one transcript that was never SYNC'd in it."""
    project = init_project(str(tmp_path / "ws"))
    for name in ["Fake_Alpha_20240101_session1_SYNC.docx", "Fake, Beta_SYNC.docx"]:
        shutil.copy(FIXTURES / name, project.data_dir / name)
    project.unsynced_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES / "unsynced" / "Fake_Gamma_Transcript.docx",
                project.unsynced_dir / "Fake_Gamma_Transcript.docx")
    run_import(project)
    return project


def synthesize_clips(project) -> pd.DataFrame:
    """Clips over every interview, timed and untimed alike, in the clip step's own schema.

    Stands in for a real `toolkit clip` run: what is being tested here is what the rest of the
    toolkit does with an untimed clip, not the model's boundary decisions.
    """
    from transcript_toolkit.core.tables import clips_path, write_deliverable

    paras = pd.read_parquet(project.paragraphs_path)
    rows = []
    for iid, g in paras.groupby("interview_id"):
        g = g.sort_values("paragraph_idx")
        idxs = g["paragraph_idx"].tolist()
        half = max(1, len(idxs) // 2)
        for k, (lo, hi) in enumerate([(idxs[0], idxs[half - 1]), (idxs[half], idxs[-1])]):
            sub = g[(g["paragraph_idx"] >= lo) & (g["paragraph_idx"] <= hi)]
            if sub.empty:
                continue
            start_ts = str(sub.iloc[0]["turn_time_start"])
            end_ts = str(sub.iloc[-1]["turn_time_start"])
            rows.append({"interview_id": iid, "clip_id": f"{iid}_{k:04d}",
                         "start_paragraph_idx": int(lo), "end_paragraph_idx": int(hi),
                         "n_paragraphs": len(sub),
                         "total_words": int(sub["word_count"].sum()),
                         "start_ts": start_ts, "end_ts": end_ts,
                         "duration_seconds": 60.0 if start_ts else None})
    df = pd.DataFrame(rows)
    write_deliverable(df, clips_path(project), sort_by="clip_id")
    return df


# --- the dataset ------------------------------------------------------------------------------

def test_the_untimed_transcript_is_in_the_collection(project):
    paras = pd.read_parquet(project.paragraphs_path)
    assert UNTIMED_ID in set(paras["interview_id"])
    assert untimed_ids(paras) == {UNTIMED_ID}


def test_it_is_eligible_for_the_demo_sample(project):
    """Nothing about it needs holding back from a demo — the steps work on it."""
    from transcript_toolkit.core.sampling import draw_interview_sample

    assert UNTIMED_ID in draw_interview_sample(project, n=3)


def test_the_clip_prompt_renders_its_lines_without_a_timestamp(project):
    """The paragraph line the model reads. A missing timestamp is left out rather than sent as
    an empty bracket, and the index — which is what a clip is identified by — is still there."""
    from transcript_toolkit.steps.clip.run import paragraph_line

    paras = pd.read_parquet(project.paragraphs_path)
    untimed = next(paras[paras["interview_id"] == UNTIMED_ID].itertuples())
    timed = next(paras[paras["interview_id"] == "fake_beta"].itertuples())

    assert paragraph_line(timed).startswith(f"[{timed.paragraph_idx}] [{timed.turn_time_start}]")
    # index, then straight to the role marker: no empty bracket standing in for the time
    assert paragraph_line(untimed).startswith(f"[{untimed.paragraph_idx}] [")
    assert "[] " not in paragraph_line(untimed)
    assert ":" not in paragraph_line(untimed).split("(")[0]


def test_chunking_an_untimed_interview_works(project):
    """Chunking is by word count. Nothing in it ever looked at a timestamp."""
    from transcript_toolkit.steps.clip.chunking import chunk_paragraphs

    paras = pd.read_parquet(project.paragraphs_path)
    untimed = paras[paras["interview_id"] == UNTIMED_ID]
    chunks = chunk_paragraphs(untimed, 100_000, 4)
    assert len(chunks) == 1 and chunks[0].shown_start == int(untimed["paragraph_idx"].min())


# --- what an untimed clip looks like downstream -----------------------------------------------

def test_an_untimed_clip_carries_no_times_and_no_duration(project):
    clips = synthesize_clips(project)
    untimed = clips[clips["interview_id"] == UNTIMED_ID]
    assert len(untimed) == 2
    assert (untimed["start_ts"] == "").all() and (untimed["end_ts"] == "").all()
    assert untimed["duration_seconds"].isna().all()
    timed = clips[clips["interview_id"] == "fake_beta"]
    assert (timed["start_ts"] != "").all()


def test_the_review_page_shows_a_paragraph_range_instead_of_a_dash(project):
    """A heading reading "–" tells a reader nothing. Where in the interview the clip sits is
    the thing the heading is for, so it says that in paragraphs instead."""
    from transcript_toolkit.core.reviewdoc import clip_span

    clips = synthesize_clips(project)
    untimed = next(c for c in clips.itertuples() if c.interview_id == UNTIMED_ID)
    timed = next(c for c in clips.itertuples() if c.interview_id == "fake_beta")
    assert clip_span(untimed) == f"¶{untimed.start_paragraph_idx}–{untimed.end_paragraph_idx}"
    assert clip_span(timed) == f"{timed.start_ts}–{timed.end_ts}"


def test_a_hand_edited_label_is_pinned_to_something_that_can_change(project):
    """An override is skipped out loud when the clip's boundaries move. Pinned to timestamps,
    an untimed clip's pin would be two empty strings on every clip in the collection — so the
    promise would quietly stop being kept exactly where it is hardest to notice."""
    clips = synthesize_clips(project)
    clip_id = f"{UNTIMED_ID}_0000"
    overrides_mod.upsert(project, clip_id, "A better label", clips)

    saved = overrides_mod.load(project).iloc[0]
    row = clips[clips["clip_id"] == clip_id].iloc[0]
    assert saved["start_ts"] == f"p{row['start_paragraph_idx']}"
    assert saved["end_ts"] == f"p{row['end_paragraph_idx']}"

    shown, complaints = overrides_mod.overlay(project, clips)
    assert shown == {clip_id: "A better label"} and not complaints

    moved = clips.copy()
    moved.loc[moved["clip_id"] == clip_id, "end_paragraph_idx"] += 1
    shown, complaints = overrides_mod.overlay(project, moved)
    assert shown == {} and len(complaints) == 1 and "span has changed" in complaints[0]


def test_a_timed_clips_pin_is_unchanged(project):
    """The pin for everything that already had one has to read exactly as it did before, or
    every existing override in every project would be dropped as a mismatch."""
    clips = synthesize_clips(project)
    clip_id = "fake_beta_0000"
    overrides_mod.upsert(project, clip_id, "Hand written", clips)
    saved = overrides_mod.load(project).iloc[0]
    row = clips[clips["clip_id"] == clip_id].iloc[0]
    assert saved["start_ts"] == row["start_ts"] and saved["end_ts"] == row["end_ts"]


# --- the spreadsheet --------------------------------------------------------------------------

def test_the_export_leaves_start_and_end_empty_for_it(project):
    """Blank is the honest answer, and it is what tells a reader of the sheet that there is no
    recording to go to."""
    from transcript_toolkit.steps.export import build_clips_sheet

    synthesize_clips(project)
    sheet, included = build_clips_sheet(project, [])
    untimed = sheet[sheet["Session"] == UNTIMED_ID]
    assert len(untimed) == 2
    assert (untimed["Start"] == "").all() and (untimed["End"] == "").all()
    assert (sheet[sheet["Session"] == "fake_beta"]["Start"] != "").all()
    assert "clips" in included


def test_the_interviews_tab_shows_when_it_was_imported(project):
    """Both piles are in the manifest, so a corrected untimed transcript is checkable against
    the sheet the same way as any other."""
    from transcript_toolkit.core import manifest as manifest_mod

    stamps = manifest_mod.imported_at(project, manifest_mod.UNSYNCED)
    assert UNTIMED_ID in stamps


def test_load_clips_sees_them_like_any_other(project):
    """Every tagging step reads the clips table and nothing else. If untimed clips are in it,
    they are tagged; there is no separate path for them to be left out of."""
    synthesize_clips(project)
    clips = load_clips(project)
    assert UNTIMED_ID in set(clips["interview_id"])
