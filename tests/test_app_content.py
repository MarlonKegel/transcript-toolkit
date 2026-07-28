"""The app's map of the CLI must match the CLI.

Everything the app can run is built in `app/content.py`. If a command or a flag is renamed in
cli.py, or a prompt is reworded in console.py, these tests fail here rather than the app
silently offering a button that errors out in front of a user.
"""
import pytest

from transcript_toolkit.app import content
from transcript_toolkit.cli import build_parser


def parses(argv: list[str]) -> None:
    """The real parser accepts it (argparse exits on a bad command, which surfaces as SystemExit)."""
    build_parser().parse_args([*argv, "--project", "/tmp/x"])


ALL_STEPS = pytest.mark.parametrize("step", content.STEPS, ids=lambda s: s.slug)


@ALL_STEPS
def test_demo_and_full_commands_are_real_commands(step):
    for demo in (True, False):
        parses(content.run_argv(step, demo=demo, set_name="fixture"))


@ALL_STEPS
def test_followup_commands_are_real_commands(step):
    for action in step.followups:
        parses(content.action_argv(action, set_name="fixture"))


def test_standalone_commands_are_real_commands():
    parses(list(content.SAMPLE.argv))
    parses(list(content.IMPORT.argv))


@ALL_STEPS
def test_full_runs_carry_no_yes_flag(step):
    """A full run must reach the CLI's own confirmation prompt: that is where the cost is
    shown and approved. `--yes` would skip it and spend the money unasked."""
    argv = content.run_argv(step, demo=False, set_name="fixture")
    assert "--yes" not in argv and "--skip-demo-check" not in argv


@ALL_STEPS
def test_batch_is_left_to_the_prompt(step):
    """The app never picks the transport itself — the user chooses at the prompt, where both
    prices are shown."""
    argv = content.run_argv(step, demo=False, set_name="fixture")
    assert "--batch" not in argv and "--no-batch" not in argv


def test_batch_capability_matches_the_cli():
    """Only the steps whose parser has --batch may advertise it."""
    parser = build_parser()
    for step in content.STEPS:
        argv = [*step.argv, "--batch", "--project", "/tmp/x"]
        try:
            parser.parse_args(argv)
            accepted = True
        except SystemExit:
            accepted = False
        assert accepted == step.batch, f"{step.slug}: --batch accepted={accepted}, declared={step.batch}"


def test_topics_needs_a_set():
    topics = content.BY_SLUG["topics"]
    with pytest.raises(ValueError):
        content.run_argv(topics, demo=True, set_name=None)
    assert content.step_key(topics, "collection") == "topics:collection"
    assert content.step_key(content.BY_SLUG["clip"]) == "clip"


def test_display_command_reads_like_the_terminal():
    step = content.BY_SLUG["topics"]
    assert content.display_command(content.run_argv(step, demo=True, set_name="collection")) == \
        "toolkit topics tag --set collection --demo"


# --- the two places the app reads CLI text ------------------------------------------------

def test_prompt_buttons_match_the_real_prompts(monkeypatch):
    """`choose_transport` and `confirm_or_abort` are what the app puts buttons under. Build
    their prompts the way console.py does and check the app still recognises them."""
    from transcript_toolkit.core import console

    seen = []
    monkeypatch.setattr(console.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": seen.append(prompt) or "1")

    console.choose_transport("Label 3 interviews.", (1.0, 0.5))
    assert content.answers_for(seen[-1]) == content.TRANSPORT_ANSWERS

    monkeypatch.setattr("builtins.input", lambda prompt="": seen.append(prompt) or "y")
    console.choose_transport("Label 3 interviews.", (1.0, 0.5), batch=True)
    assert content.answers_for(seen[-1]) == content.YES_NO_ANSWERS

    console.confirm_or_abort("Clip 3 interviews?")
    assert content.answers_for(seen[-1]) == content.YES_NO_ANSWERS


def test_answers_for_ignores_ordinary_output():
    assert content.answers_for("Labeling 43 interviews") is None
    assert content.answers_for("") is None


def test_missing_demo_offers_the_demo_button(tmp_path):
    """The demo gate's own message, straight from state.py."""
    from transcript_toolkit.errors import ToolkitError
    from transcript_toolkit.project import init_project
    from transcript_toolkit.state import check_demo_gate, record_demo

    project = init_project(str(tmp_path / "ws"))
    with pytest.raises(ToolkitError) as none_yet:
        check_demo_gate(project, "clip", "abc", demo_command="toolkit clip --demo")
    assert content.fix_for(str(none_yet.value)) == "demo"

    record_demo(project, "clip", "abc", units=["a"], diag="d.html")
    with pytest.raises(ToolkitError) as stale:
        check_demo_gate(project, "clip", "different", demo_command="toolkit clip --demo")
    assert content.fix_for(str(stale.value)) == "demo"


def test_missing_sample_offers_the_sample_button(tmp_path):
    """The sample prerequisite's own message, straight from core/sampling.py."""
    from transcript_toolkit.core.sampling import load_interview_sample
    from transcript_toolkit.errors import ToolkitError
    from transcript_toolkit.project import init_project

    project = init_project(str(tmp_path / "ws"))
    with pytest.raises(ToolkitError) as e:
        load_interview_sample(project)
    assert content.fix_for(str(e.value)) == "sample"


def test_unremarkable_errors_offer_no_button():
    assert content.fix_for("No .docx transcripts found under data/") is None
