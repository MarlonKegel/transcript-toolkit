"""Two things the app reads back out of the toolkit rather than working out for itself: how far a
run has got, and which prompt a step is sending.
"""
import pytest

from transcript_toolkit.app import content
from transcript_toolkit.core import prompts
from transcript_toolkit.project import init_project


@pytest.fixture
def project(tmp_path):
    return init_project(str(tmp_path / "ws"))


# --- how far a run has got --------------------------------------------------------------------

def test_progress_is_read_off_the_lines_the_steps_actually_print():
    """Every step counts its work off as `  [3/12] ...`. The bar in the app is that count read
    back, so this builds the line the same way the steps do."""
    iid, i, total = "fake_beta", 3, 12
    printed = f"  [{i}/{total}] [{'cached'}] {iid}: clips=4 words=100"
    assert content.progress_of([printed]) == (3, 12)


def test_the_latest_count_wins():
    lines = ["Clipping 12 interview(s)", "  [1/12] a", "  [2/12] b", "note", "  [7/12] c"]
    assert content.progress_of(lines) == (7, 12)


def test_the_batch_apis_own_polling_line_is_not_a_count():
    """`core/batch` prints `  [   42s] status=in_progress` while it waits. Reading that as 42 of
    something would put a bar on screen that means nothing."""
    assert content.progress_of(["  [   42s] status=in_progress  done=0"]) is None


def test_nothing_to_report_before_the_first_unit_finishes():
    assert content.progress_of([]) is None
    assert content.progress_of(["Clipping 12 interview(s) · gpt-5.6-sol/medium"]) is None


def test_a_nonsense_count_is_ignored():
    assert content.progress_of(["  [0/0] x"]) is None
    assert content.progress_of(["  [13/12] x"]) is None


# --- which prompt a step sends ----------------------------------------------------------------

def test_every_prompted_step_names_a_prompt_that_is_in_the_workspace(project):
    for step in prompts.PROMPTED_STEPS:
        path = prompts.prompt_path(project, step)
        assert path.exists(), f"{step}: {path} is not there"
        assert prompts.load_prompt(project, prompts.prompt_name(project, step)).strip()


def test_a_step_with_no_prompt_says_so(project):
    for step in ("import", "export"):
        with pytest.raises(ValueError):
            prompts.prompt_name(project, step)


def test_a_topic_list_may_bring_its_own_rubric(project):
    """A set can override the shared prompt. The app must show the file the run will read, not
    the default one."""
    project.config_path.write_text(
        project.config_path.read_text().replace(
            "sets: {}",
            "sets:\n    strict:\n      file: topics/strict.csv\n      prompt: tag_topics_strict.md"))
    assert prompts.prompt_name(project, "topics") == "tag_topics.md"
    assert prompts.prompt_name(project, "topics", "strict") == "tag_topics_strict.md"


def test_status_says_which_file_to_edit_for_each_step(project, capsys):
    """A terminal user gets the same answer the app's prompt editor gives: `toolkit status` names
    the file, so nobody has to guess which of prompts/ belongs to which step."""
    from transcript_toolkit.steps.status import gather_status, run_status

    assert gather_status(project)["prompts"]["clip"] == "clip_interview.md"
    run_status(project)
    printed = capsys.readouterr().out
    assert "prompts/clip_interview.md" in printed
    assert "--reset-prompt" in printed


def test_the_addendums_offered_are_the_files_that_are_there(project):
    """`label.addendum` points at a file in prompts/. The app offers the ones that exist rather
    than a free-text box that can name a file that does not."""
    offered = prompts.addendums(project)
    assert "prompt_addendums/justify_topics.md" in offered
    for name in offered:
        assert (project.prompts_dir / name).is_file()
