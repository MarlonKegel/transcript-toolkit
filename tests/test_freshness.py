"""Whether running something again would do anything.

This decides which buttons the app greys out, so being wrong in the wrong direction is
expensive: a run that was needed and looked done is a wrong deliverable, or an unnoticed
half-tagged collection. Every case here is one of the ways that could happen.
"""
import shutil
from pathlib import Path

import pandas as pd
import pytest

from transcript_toolkit.core.tables import clips_path, write_deliverable
from transcript_toolkit.project import init_project
from transcript_toolkit.state import record_demo, record_full
from transcript_toolkit.steps import freshness as fresh
from transcript_toolkit.steps.import_ import run_import

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def project(tmp_path):
    project = init_project(str(tmp_path / "ws"))
    for name in ["Fake_Alpha_20240101_session1_SYNC.docx",
                 "Fake_Alpha_20240108_session2_SYNC.docx",
                 "Fake, Beta_SYNC.docx"]:
        shutil.copy(FIXTURES / name, project.data_dir / name)
    run_import(project)
    return project


def clips(project, n: int = 6) -> None:
    rows = [{"clip_id": f"fake_beta_{i:04d}", "interview_id": "fake_beta",
             "start_paragraph_idx": i, "end_paragraph_idx": i, "n_paragraphs": 1,
             "total_words": 10, "start_ts": "", "end_ts": "", "duration_seconds": 1.0}
            for i in range(1, n + 1)]
    write_deliverable(pd.DataFrame(rows), clips_path(project), sort_by="clip_id")


def wrote(project, rel: str) -> None:
    path = project.outputs_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x")


# --- a step's own runs -------------------------------------------------------------------

def test_nothing_run_is_nothing_to_report(project):
    state = fresh.freshness(project, "clip")
    assert state["demo"] == fresh.NONE and state["full"] == fresh.NONE
    assert state["fingerprint"]


def test_a_run_with_the_same_fingerprint_is_current(project):
    now = fresh.current_fingerprint(project, "clip")
    record_full(project, "clip", now, model="m", n_units=3)      # every fixture interview
    wrote(project, "clips/clips.parquet")
    assert fresh.freshness(project, "clip")["full"] == fresh.CURRENT


def test_editing_the_prompt_makes_it_stale_again(project):
    now = fresh.current_fingerprint(project, "clip")
    record_full(project, "clip", now, model="m", n_units=2)
    wrote(project, "clips/clips.parquet")

    prompt = project.prompts_dir / "clip_interview.md"
    prompt.write_text(prompt.read_text() + "\n\nOne more rule.\n")
    assert fresh.freshness(project, "clip")["full"] == fresh.STALE


def test_a_deleted_deliverable_means_there_is_work_to_do(project):
    """Re-running is repair, not waste: the calls are cached, and it writes the file back."""
    now = fresh.current_fingerprint(project, "clip")
    record_full(project, "clip", now, model="m", n_units=2)
    assert fresh.freshness(project, "clip")["full"] == fresh.NONE


def test_more_transcripts_than_the_last_run_covered(project):
    """Nothing about the instructions changed, so the fingerprint still matches — but there are
    interviews nobody has clipped. Calling that done would leave them out of the collection."""
    now = fresh.current_fingerprint(project, "clip")
    wrote(project, "clips/clips.parquet")
    record_full(project, "clip", now, model="m", n_units=3)
    assert fresh.freshness(project, "clip")["full"] == fresh.CURRENT
    record_full(project, "clip", now, model="m", n_units=1)
    assert fresh.freshness(project, "clip")["full"] == fresh.PARTIAL


def test_a_locations_run_is_judged_by_what_it_writes_itself(project):
    """`toolkit status` calls `locations` done once clip_countries.parquet exists — and that is
    written by `locations map`, one command later. Judging the tagging by it would report the
    step undone straight after it was paid for."""
    clips(project)
    now = fresh.current_fingerprint(project, "locations")
    record_full(project, "locations", now, model="m", n_units=6)
    wrote(project, "locations/clip_locations.parquet")
    assert fresh.freshness(project, "locations")["full"] == fresh.CURRENT


def test_a_demo_whose_review_page_is_gone_is_not_done(project):
    now = fresh.current_fingerprint(project, "clip")
    page = project.diags_dir / "clip"
    page.mkdir(parents=True, exist_ok=True)
    record_demo(project, "clip", now, units=["a"], diag=str(page))
    assert fresh.freshness(project, "clip")["demo"] == fresh.CURRENT
    shutil.rmtree(page)
    assert fresh.freshness(project, "clip")["demo"] == fresh.NONE


def test_a_topic_list_is_judged_on_its_own(project):
    (project.topics_dir / "main.csv").write_text(
        "name,description\nEducation,Schooling.\nCareer,Jobs.\n")
    clips(project)
    now = fresh.current_fingerprint(project, "topics", "main")
    record_full(project, "topics:main", now, model="m", n_units=6)
    wrote(project, "topics/main_clip_topics_wide.parquet")
    assert fresh.freshness(project, "topics", "main")["full"] == fresh.CURRENT

    # a second list has run nothing, however far the first one has got
    (project.topics_dir / "other.csv").write_text("name,description\nWork,About work.\n")
    assert fresh.freshness(project, "topics", "other")["full"] == fresh.NONE

    # and editing the first list's spreadsheet stales only that one
    (project.topics_dir / "main.csv").write_text(
        "name,description\nEducation,Schooling and training.\nCareer,Jobs.\n")
    assert fresh.freshness(project, "topics", "main")["full"] == fresh.STALE


def test_something_unreadable_claims_nothing(project):
    """A topic list that is not there yet has no fingerprint, so nothing is called done and the
    run itself gets to report the real problem."""
    state = fresh.freshness(project, "topics", "nope")
    assert state["fingerprint"] is None
    assert state["demo"] == fresh.NONE and state["full"] == fresh.NONE


# --- the free steps that follow ------------------------------------------------------------

def test_a_rollup_is_done_until_its_input_or_the_settings_change(project):
    import os
    import time

    wrote(project, "topics/main_clip_topics_wide.parquet")
    time.sleep(0.01)
    wrote(project, "topics/main_interview_topics_wide.parquet")
    assert fresh.derived_state(project, "topics", "rollup", "main") == fresh.CURRENT

    # the clip tags were run again
    later = time.time() + 10
    os.utime(project.outputs_dir / "topics" / "main_clip_topics_wide.parquet", (later, later))
    assert fresh.derived_state(project, "topics", "rollup", "main") == fresh.STALE


def test_changing_a_setting_puts_the_rollup_back(project):
    """The rule lives in config.yaml, so touching that file is what says 'decide again'."""
    import os
    import time

    wrote(project, "topics/main_clip_topics_wide.parquet")
    wrote(project, "topics/main_interview_topics_wide.parquet")
    later = time.time() + 10
    os.utime(project.config_path, (later, later))
    assert fresh.derived_state(project, "topics", "rollup", "main") == fresh.STALE


def test_a_rollup_that_has_never_run_is_not_done(project):
    wrote(project, "topics/main_clip_topics_wide.parquet")
    assert fresh.derived_state(project, "topics", "rollup", "main") == fresh.NONE


def test_only_the_free_deterministic_moves_are_judged_this_way():
    """The decision aid is meant to be run again with different variants, and re-rendering the
    review pages is the fix for pages that went stale — neither is ever 'already done'."""
    assert ("topics", "thresholds") not in fresh.DERIVED
    assert ("locations", "thresholds") not in fresh.DERIVED
    for step in ("clip", "label", "summarize", "topics", "locations"):
        assert (step, "annotate") not in fresh.DERIVED
