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
def test_every_button_on_a_step_page_is_a_real_command(step):
    for action in content.runnable(step):
        parses(content.action_argv(action, set_name="fixture"))


@ALL_STEPS
def test_what_to_compare_becomes_real_flags(step):
    """The comparison's boxes turn into flags on the real command; a typo here would only show
    up as a run that dies in the terminal."""
    asked = {"bins": "5,9", "ranges": "10-30,20-40", "flat": "20,30,40"}
    for action in content.runnable(step):
        if action.options == "compare":
            parses(content.compare_argv(action, "fixture", asked))
            # an empty box means "whatever the project says", which is the flag left off
            assert content.compare_argv(action, "fixture", {"bins": " "}) == \
                content.action_argv(action, "fixture")


def test_standalone_commands_are_real_commands():
    parses(list(content.SAMPLE.argv))
    parses(list(content.IMPORT.argv))
    parses(list(content.UNSYNCED_IMPORT.argv))
    parses(content.unsynced_argv(demo=True))
    parses(content.unsynced_argv(demo=False))


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


# --- what the pages read out of a workspace -------------------------------------------------

def test_review_pages_are_the_files_the_steps_really_write(tmp_path):
    """Every step names its review pages differently, and topics writes one set per topic list.
    Getting this wrong shows either no link at all or a page of nonsense links."""
    from transcript_toolkit.app.pages.step import diag_pages
    from transcript_toolkit.project import init_project

    project = init_project(str(tmp_path / "ws"))
    written = {
        "clip/index.html": "clip",
        "label/index.html": "label",
        "summarize/summaries.html": "summarize",
        "topics/collection_index.html": "topics",
        "locations/locations.html": "locations",
    }
    for rel in written:
        path = project.diags_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<h1>x</h1>")

    for slug in ("clip", "label", "summarize", "topics", "locations"):
        step = content.BY_SLUG[slug]
        pages = diag_pages(project, step, "collection")
        assert pages, f"{slug}: no review page found"
        for _, url in pages:
            assert (project.diags_dir / url.removeprefix("/diags/")).exists()

    # and a set the user has not tagged yet must not borrow another set's pages
    assert diag_pages(project, content.BY_SLUG["topics"], "other") == []


def test_a_topic_set_that_lives_only_in_the_config_is_still_offered(tmp_path, monkeypatch):
    """`available_sets` reads the topics section, not the whole file. Handing it the root
    config drops every set whose spreadsheet is not sitting in topics/ under its own name."""
    from transcript_toolkit.app.context import AppContext
    from transcript_toolkit.project import init_project

    project = init_project(str(tmp_path / "ws"))
    (project.topics_dir / "moved.csv").write_text("name,description\nA,B\n")
    project.config_path.write_text(
        project.config_path.read_text().replace(
            "sets: {}", "sets:\n    collection:\n      file: topics/moved.csv"))

    context = AppContext()
    context.project = project
    assert context.topic_sets() == ["collection", "moved"]


def test_quitting_is_refused_while_something_is_running(monkeypatch):
    from transcript_toolkit.app import server
    from transcript_toolkit.app.context import CONTEXT

    assert server.refuse_quit_reason() is None
    monkeypatch.setattr(type(CONTEXT.jobs), "busy", property(lambda self: True))
    monkeypatch.setattr(CONTEXT.jobs, "current",
                        type("J", (), {"title": "Label — full run"})())
    assert "Label — full run" in server.refuse_quit_reason()


def test_the_dashboard_counts_a_step_done_when_the_step_says_so(tmp_path, monkeypatch):
    """`locations tag` records its own full run, but the file `toolkit status` counts as the
    locations deliverable is written by `locations map`, one command later. Judging by the
    file alone would keep telling someone to re-run the step they just paid for."""
    from transcript_toolkit.app import stage
    from transcript_toolkit.app.context import CONTEXT
    from transcript_toolkit.project import init_project

    project = init_project(str(tmp_path / "ws"))
    (project.topics_dir / "main.csv").write_text("name,description\nA,B\n")
    (project.root / ".env").write_text("OPENAI_API_KEY=sk-x\n")
    (project.data_dir / "a.docx").write_text("x")
    monkeypatch.setattr(CONTEXT, "project", project)

    done = {"full": {"at": "2026-07-28T10:00:00+00:00"}}
    status = {"imported": True, "docx_files": 1, "deliverables": ["clips"],
              "steps": {"clip": done, "label": done, "summarize": done,
                        "topics:main": done, "locations": done}}

    for step in content.STEPS:
        assert stage.ran_fully(status, step, "main"), step.slug
    # locations counts as done from its own record, though `map` has not run and so the
    # locations deliverable is not on disk
    assert "locations" not in status["deliverables"]
    assert stage.next_action(status, project, ["main"])[2] == "/export"

    status["steps"].pop("locations")
    assert stage.next_action(status, project, ["main"])[2] == "/step/locations"


# --- the status slot's one dangerous decision ------------------------------------------------

class FakeJob:
    def __init__(self, id, live):
        self.id, self.live = id, live


def fresh_slot() -> dict:
    return {"id": None, "revision": -1, "finished": None, "fresh": True}


def watch(seen: dict, job) -> bool:
    from transcript_toolkit.app.pages.common import finished_now, note

    note(seen, job)
    return finished_now(seen, job)


def test_a_finished_run_is_announced_once():
    seen = fresh_slot()
    assert not watch(seen, FakeJob("j1", live=True))
    assert watch(seen, FakeJob("j1", live=False))
    assert not watch(seen, FakeJob("j1", live=False))       # and not again on every tick


def test_a_run_that_was_already_over_is_not_announced():
    """The status slot lives inside the section it asks to be rebuilt, so finishing a run
    replaces the slot. If the replacement announced the same finish, the page would rebuild
    itself forever — which is what this rules out."""
    for _ in range(3):                                      # what a loop would look like
        seen = fresh_slot()
        assert not watch(seen, FakeJob("j1", live=False))


def test_a_later_run_is_announced_even_if_it_is_over_in_one_tick():
    """A slot that existed before the run started reports it, however quick it was — some of
    these finish in well under one tick."""
    seen = fresh_slot()
    assert not watch(seen, FakeJob("j1", live=False))       # was over before the slot appeared
    assert watch(seen, FakeJob("j2", live=False))           # this one began while it watched


# --- knowing an update actually changed something --------------------------------------------

def test_the_update_marker_is_the_one_the_command_prints():
    """The app restarts itself on this line, so it has to be the line `toolkit update` really
    writes — not a description of it."""
    from transcript_toolkit.core import update

    changed = [f"{update.UPDATED_MARKER} 0.2.9 -> 0.3.0", "Check it with:  toolkit --version"]
    assert content.updated_version(changed) == "0.3.0"

    unchanged = [update.UNCHANGED_MARKER, "Check it with:  toolkit --version"]
    assert content.updated_version(unchanged) is None
    assert content.updated_version([]) is None
    assert content.updated_version(["Updating https://github.com/…"]) is None
