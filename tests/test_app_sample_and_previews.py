"""The demo sample chooser, the previews, and the buttons that should not be clickable.

All three are places where the app used to leave someone to read the terminal to find out what
happened — or let them start something that could only fail.
"""
import shutil
from pathlib import Path

import pytest

from transcript_toolkit.app import content
from transcript_toolkit.core.sampling import DEFAULT_N, draw_interview_sample
from transcript_toolkit.errors import ToolkitError
from transcript_toolkit.project import init_project
from transcript_toolkit.steps.import_ import run_import

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def imported(tmp_path):
    project = init_project(str(tmp_path / "ws"))
    for docx in FIXTURES.glob("*.docx"):
        shutil.copy(docx, project.data_dir)
    run_import(project)
    return project


# --- choosing the demo interviews ------------------------------------------------------------

def test_naming_interviews_without_a_size_gives_exactly_those(imported):
    """Unchanged behaviour: `toolkit sample --interviews a,b` is still "these two"."""
    sample = draw_interview_sample(imported, explicit=["fake_beta"])
    assert sample == ["fake_beta"]


def test_naming_some_and_asking_for_more_fills_the_rest_at_random(imported):
    """What the app's "choose a couple, draw the rest" option needs, in the CLI where it
    belongs — the app must not do its own sampling."""
    available = sorted(draw_interview_sample(imported, n=99))
    assert len(available) >= 3

    sample = draw_interview_sample(imported, n=3, explicit=["fake_beta"])
    assert len(sample) == 3
    assert "fake_beta" in sample
    assert set(sample) <= set(available)


def test_asking_for_fewer_than_you_named_keeps_the_ones_you_named(imported):
    sample = draw_interview_sample(imported, n=1, explicit=["fake_beta", "fake_alpha_20240101_session1"])
    assert sorted(sample) == ["fake_alpha_20240101_session1", "fake_beta"]


def test_an_unknown_interview_is_refused_by_name(imported):
    with pytest.raises(ToolkitError, match="Unknown interview id"):
        draw_interview_sample(imported, n=2, explicit=["nobody"])


def test_the_app_offers_the_same_default_the_cli_draws():
    """Three numbers that must never disagree: what the app puts in the box, and the sizes the
    CLI will actually draw."""
    from transcript_toolkit.core.sampling import MAX_N, MIN_N
    assert content.SAMPLE_DEFAULT_N == DEFAULT_N
    assert (content.SAMPLE_MIN_N, content.SAMPLE_MAX_N) == (MIN_N, MAX_N)
    assert MIN_N < DEFAULT_N < MAX_N


def test_the_sample_command_refuses_a_size_that_is_not_a_demo(imported):
    """The app will not offer a sample outside these bounds, and neither will the command it
    runs — so somebody typing it themselves meets the same rule."""
    from transcript_toolkit.cli import build_parser

    def draw(*argv):
        args = build_parser().parse_args(["sample", *argv, "--project", str(imported.root)])
        args.func(args)

    with pytest.raises(ToolkitError, match="at least 3"):
        draw("--n", "2")
    with pytest.raises(ToolkitError, match="at most 10"):
        draw("--n", "11")
    draw("--n", "3")
    assert len(imported.demo_sample_path.read_text().split()) == 3


def test_the_sample_command_the_app_builds_is_a_real_command():
    from transcript_toolkit.cli import build_parser

    argv = content.sample_argv(7, ["a", "b"])
    args = build_parser().parse_args([*argv, "--project", "/tmp/x"])
    assert args.n == 7 and args.interviews == "a,b"
    assert "--interviews" not in content.sample_argv(5)


# --- the previews ----------------------------------------------------------------------------

def test_the_chunk_preview_the_app_draws_is_what_the_terminal_prints(imported, capsys):
    """One calculation, two renderings. If these could drift, the table in the app would be a
    second opinion about what is going to be sent."""
    from transcript_toolkit.steps.clip import chunk_preview, preview_chunks

    data = chunk_preview(imported)
    assert data["rows"] and set(data["rows"][0]) == {
        "interview_id", "n_para", "est_total_tokens", "n_chunks", "layout"}
    assert sum(data["distribution"].values()) == len(data["rows"])

    preview_chunks(imported)
    printed = capsys.readouterr().out
    assert f"threshold={data['threshold']}" in printed
    for row in data["rows"]:
        assert row["interview_id"] in printed
        assert row["layout"] in printed


def test_the_batch_preview_the_app_draws_is_what_the_terminal_prints(imported, capsys, monkeypatch):
    from transcript_toolkit.steps.label import run as label_run

    clips = _fake_clips(imported)
    monkeypatch.setattr(label_run, "load_clips", lambda _p: clips)
    batch_preview, preview_batches = label_run.batch_preview, label_run.preview_batches

    data = batch_preview(imported)
    assert data["rows"] and data["clips_per_batch"]
    preview_batches(imported)
    printed = capsys.readouterr().out
    for row in data["rows"]:
        assert row["layout"] in printed


def _fake_clips(project):
    """One clip per interview, enough for the batch planner to have something to lay out."""
    import pandas as pd

    paragraphs = pd.read_parquet(project.paragraphs_path)
    rows = []
    for iid, sub in paragraphs.groupby("interview_id"):
        rows.append({"clip_id": f"{iid}_01", "interview_id": iid,
                     "start_paragraph_idx": int(sub["paragraph_idx"].min()),
                     "end_paragraph_idx": int(sub["paragraph_idx"].max())})
    return pd.DataFrame(rows)


# --- buttons that would only fail --------------------------------------------------------------

def test_an_action_with_nothing_to_read_is_reported_as_unavailable():
    """`clip annotate` re-renders the review pages from saved clips. With no clips it can only
    print an error, so the page disables it instead of letting someone find that out."""
    clip = content.BY_SLUG["clip"]
    annotate = next(a for a in clip.extras if a.slug == "annotate")
    assert content.missing_for(annotate, []) == ["clips"]
    assert content.missing_for(annotate, ["clips"]) == []


def test_per_set_actions_ask_about_their_own_set():
    topics = content.BY_SLUG["topics"]
    rollup = next(a for a in content.runnable(topics) if a.slug == "rollup")
    assert content.missing_for(rollup, ["topics:collection"], "collection") == []
    assert content.missing_for(rollup, ["topics:other"], "collection") == ["topics:collection"]


def test_every_action_that_reads_a_deliverable_declares_it():
    """A new action added without `needs` would quietly go back to failing in the terminal."""
    reads_something = {("clip", "annotate"), ("label", "annotate"), ("summarize", "annotate"),
                       ("topics", "rollup"), ("topics", "annotate"), ("topics", "thresholds"),
                       ("locations", "map"), ("locations", "rollup"), ("locations", "annotate"),
                       ("locations", "thresholds"), ("label", "preview")}
    for step in content.STEPS:
        for action in content.runnable(step):
            if (step.slug, action.slug) in reads_something:
                assert action.needs, f"{step.slug} {action.slug} declares no prerequisite"


def test_the_things_nobody_needs_are_out_of_the_way():
    """Chunking and batching explain how the step works; they are not part of doing it, so they
    are among the extras at the foot of the page and not in the numbered flow."""
    for slug in ("clip", "label"):
        step = content.BY_SLUG[slug]
        preview = next(a for a in step.extras if a.slug == "preview")
        assert preview.explain and preview.preview
        assert "preview" not in [a.slug for a in step.sequels]
    locations = content.BY_SLUG["locations"]
    assert "survey" in [a.slug for a in locations.extras]


def test_rolling_up_is_deciding_then_doing():
    """The order is the work. Seeing what each way of deciding would tag comes first; picking
    the rule is part of the run that uses it, not a move of its own — a rollup with the decision
    buried inside it and no way to see it is the thing this replaced."""
    for slug in ("topics", "locations"):
        moves = content.BY_SLUG[slug].sequels
        assert [m.slug for m in moves][-2:] == ["thresholds", "rollup"]
        compare = next(m for m in moves if m.slug == "thresholds")
        assert compare.reviews and compare.options == "compare" and compare.explain
        assert next(m for m in moves if m.slug == "rollup").setting == "rollup"
        assert "thresholds" not in [a.slug for a in content.BY_SLUG[slug].extras]


def test_the_comparison_leaves_a_page_to_read():
    """A decision aid whose whole output is a line in the terminal is not one."""
    for slug in ("topics", "locations"):
        compare = next(m for m in content.BY_SLUG[slug].sequels
                       if getattr(m, "slug", "") == "thresholds")
        assert [r.filename for r in compare.reviews] == \
            [f"{'{set}' if slug == 'topics' else slug}_thresholds.html"]
