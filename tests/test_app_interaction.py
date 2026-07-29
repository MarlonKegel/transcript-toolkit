"""Clicking things.

The pages render correctly (test_app_pages.py) and the runner works (test_app_jobs.py); this
is the join between them — that a button really starts the command it names, and that the run
panel then shows it.
"""
import asyncio
import shutil
from pathlib import Path

import pytest
from nicegui.testing import User

from transcript_toolkit.app import jobs
from transcript_toolkit.app.context import CONTEXT


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def open_workspace(tmp_path, monkeypatch):
    """A workspace with transcripts imported, open in the app, with a stub child so clicking
    Run spends nothing."""
    from transcript_toolkit.project import init_project
    from transcript_toolkit.steps.import_ import run_import

    project = init_project(str(tmp_path / "ws"))
    for docx in FIXTURES.glob("*.docx"):
        shutil.copy(docx, project.data_dir)
    run_import(project)

    monkeypatch.setattr(CONTEXT, "project", project)
    monkeypatch.setattr(CONTEXT, "jobs", jobs.JobManager())
    return project


@pytest.fixture
def echo_child(monkeypatch):
    """Replace the CLI with a child that prints the arguments it was given, so a test can see
    exactly what a button would have run."""
    import sys
    monkeypatch.setattr(jobs, "CHILD_COMMAND", [
        sys.executable, "-u", "-c",
        "import sys; print('RAN', ' '.join(sys.argv[1:]))",
    ])


async def settle(user: User, seconds: float = 1.5) -> None:
    import asyncio
    await asyncio.sleep(seconds)
    await user.should_see("Transcript Toolkit")


@pytest.mark.asyncio
async def test_the_demo_button_runs_the_demo_command(user: User, open_workspace, echo_child):
    await user.open("/step/clip")
    await user.should_see("Run the demo")
    user.find("Run the demo").click()
    await settle(user)

    job = CONTEXT.jobs.current
    assert job is not None
    assert job.command == "toolkit clip --demo"
    assert any("RAN clip --demo --project" in line for line in job.lines), list(job.lines)


@pytest.mark.asyncio
async def test_the_full_run_button_lets_the_cli_ask_about_money(user: User, open_workspace,
                                                                echo_child):
    """No --yes and no --batch: the confirmation prompt is the CLI's, and so are its figures."""
    await user.open("/step/label")
    user.find("Run on the whole collection").click()
    await settle(user)

    job = CONTEXT.jobs.current
    assert job.command == "toolkit label"
    assert "--yes" not in job.text() and "--batch" not in job.text()


@pytest.mark.asyncio
async def test_a_second_run_is_refused_while_one_is_live(user: User, open_workspace, monkeypatch):
    import sys
    monkeypatch.setattr(jobs, "CHILD_COMMAND",
                        [sys.executable, "-u", "-c", "import time; time.sleep(10)"])
    await user.open("/step/clip")
    user.find("Run the demo").click()
    await settle(user)
    user.find("Run the demo").click()
    await settle(user)
    await user.should_see("still running")
    await CONTEXT.jobs.stop()


@pytest.mark.asyncio
async def test_the_workspace_page_saves_a_key(user: User, open_workspace):
    from transcript_toolkit.app import workspaces

    await user.open("/workspace")
    await user.should_see("No key yet")
    user.find("Paste a key").type("sk-test-value")
    user.find("Save key").click()
    await settle(user)
    assert workspaces.has_api_key(open_workspace)


@pytest.mark.asyncio
async def test_the_dashboard_points_at_the_first_thing_to_do(user: User, open_workspace):
    await user.open("/")
    await user.should_see("Add your OpenAI key")
    await user.should_see("Clip")


@pytest.mark.asyncio
async def test_with_no_workspace_open_every_page_leads_to_the_workspace_page(user: User,
                                                                            monkeypatch):
    """First run: the app has nothing open, so wherever someone lands they are taken to the
    page that gets them started."""
    monkeypatch.setattr(CONTEXT, "project", None)
    for path in ("/", "/step/clip", "/export"):
        await user.open(path)
        await user.should_see("Start a new project")


@pytest.mark.asyncio
async def test_a_run_survives_the_page_being_left_and_come_back_to(user: User, open_workspace,
                                                                  monkeypatch):
    """The headline of the whole design: the run lives on the server, not in the tab. Close the
    window mid-run, come back, and it is still going with its output intact."""
    import sys
    monkeypatch.setattr(jobs, "CHILD_COMMAND", [sys.executable, "-u", "-c", (
        "import time\n"
        "print('halfway through something long')\n"
        "time.sleep(20)\n")])

    await user.open("/step/clip")
    user.find("Run the demo").click()
    await settle(user)
    job = CONTEXT.jobs.current
    assert job.live

    await user.open("/export")                     # wander off
    await user.open("/step/clip")                  # and come back
    await settle(user)

    assert CONTEXT.jobs.current is job             # the same run, not a new one
    assert job.live
    await user.should_see("halfway through something long")
    await user.should_see("Stop")

    await CONTEXT.jobs.stop()
    while job.live:
        import asyncio
        await asyncio.sleep(0.05)
    assert job.state == jobs.STOPPED


@pytest.mark.asyncio
async def test_a_failed_run_offers_the_step_that_was_skipped(user: User, open_workspace):
    """A full run with no demo behind it is refused by the CLI; the app turns that into the
    button that fixes it rather than leaving the user to read a command."""
    await user.open("/step/clip")
    user.find("Run on the whole collection").click()
    await settle(user, 6.0)

    job = CONTEXT.jobs.current
    assert job.state == jobs.FAILED, job.state
    await user.should_see("No demo run recorded")
    await user.should_see("Run the demo")


def _upload_element(user: User):
    """The page's upload box, as NiceGUI's own element."""
    from nicegui.elements.upload import Upload
    return list(user.find(kind=Upload).elements)[0]


async def _drop(user: User, name: str, data: bytes) -> None:
    """Drop a file on it exactly the way the browser does — NiceGUI's own event, its own
    payload type. Calling a handler with a hand-made object would only prove the object."""
    from nicegui.elements.upload_files import SmallFileUpload
    await _upload_element(user).handle_uploads(
        [SmallFileUpload(name=name, content_type="application/octet-stream", _data=data)])
    await asyncio.sleep(0.3)        # the handler is async; NiceGUI runs it as a task


@pytest.mark.asyncio
async def test_dropping_a_transcript_puts_it_where_import_looks(user: User, open_workspace):
    """The first thing anyone does with the app. It has to actually write the file."""
    await user.open("/workspace")
    await _drop(user, "Newcomer_SYNC.docx", b"pretend docx")
    assert (open_workspace.data_dir / "Newcomer_SYNC.docx").read_bytes() == b"pretend docx"


@pytest.mark.asyncio
async def test_dropping_a_transcript_twice_refuses_rather_than_replaces(user: User,
                                                                       open_workspace):
    await user.open("/workspace")
    await _drop(user, "Twice_SYNC.docx", b"first")
    await _drop(user, "Twice_SYNC.docx", b"second")
    assert (open_workspace.data_dir / "Twice_SYNC.docx").read_bytes() == b"first"
    await user.should_see("already in this project")


async def _drop_many(user: User, files: dict[str, bytes]) -> None:
    """One drop of several files, the way selecting eight in Finder arrives."""
    from nicegui.elements.upload_files import SmallFileUpload
    await _upload_element(user).handle_uploads(
        [SmallFileUpload(name=name, content_type="application/octet-stream", _data=data)
         for name, data in files.items()])
    await asyncio.sleep(0.5)


@pytest.mark.asyncio
async def test_dropping_eight_transcripts_at_once_keeps_and_shows_all_eight(user: User,
                                                                            open_workspace):
    """Dropping eight used to land most of them and then say "2 .docx in this project".

    The count was read once when the section was drawn, and every file's handler separately
    rebuilt the section it was being uploaded into, so eight concurrent redraws raced and an
    early one won. Now one handler takes the whole drop and the list is redrawn once, after.
    """
    await user.open("/workspace")
    before = {p.name for p in open_workspace.data_dir.glob("*.docx")}
    files = {f"Person{i}_SYNC.docx": f"body {i}".encode() for i in range(8)}
    await _drop_many(user, files)

    landed = {p.name for p in open_workspace.data_dir.glob("*.docx")}
    assert set(files) <= landed, sorted(set(files) - landed)
    for name, data in files.items():
        assert (open_workspace.data_dir / name).read_bytes() == data
    # and the page says so, rather than a number from before the drop
    await user.should_see(f"{len(before) + len(files)} transcripts in this project")


@pytest.mark.asyncio
async def test_the_transcript_list_shows_what_has_been_imported(user: User, open_workspace):
    """Answering "did my drop work, and do I still need to press Import?" on the page itself."""
    await user.open("/workspace")
    await user.should_see("all imported")
    await _drop_many(user, {"Newcomer_SYNC.docx": b"x"})
    await user.open("/workspace")
    await user.should_see("Newcomer_SYNC.docx")
    await user.should_see("not imported yet")


@pytest.mark.asyncio
async def test_importing_when_there_is_nothing_new_says_so_instead_of_running(user: User,
                                                                             open_workspace):
    await user.open("/workspace")
    user.find("Import").click()
    await settle(user)
    await user.should_see("Everything is already imported")
    assert CONTEXT.jobs.current is None


@pytest.mark.asyncio
async def test_dropping_a_topic_list_creates_the_set(user: User, open_workspace):
    """Uploading a topic list is the only way to make a set from inside the app."""
    await user.open("/step/topics")
    await user.should_see("No topic list yet")
    await _drop(user, "collection.csv", b"name,description\nWork,About work\n")
    assert (open_workspace.topics_dir / "collection.csv").exists()

    await user.open("/step/topics")
    await user.should_see("Run the demo")               # the set exists now


@pytest.mark.asyncio
async def test_every_page_survives_the_project_folder_being_deleted(user: User, open_workspace):
    """The reported failure: with the folder gone, Settings returned a 500 with a raw
    FileNotFoundError. No page may read a file out of a project that is not there."""
    import shutil
    shutil.rmtree(open_workspace.root)

    for path in ("/", "/settings", "/export", "/workspace", "/step/clip", "/step/topics"):
        await user.open(path)
        await user.should_see("Transcript Toolkit")


@pytest.mark.asyncio
async def test_a_deleted_project_offers_the_two_things_that_happened(user: User, open_workspace):
    import shutil
    shutil.rmtree(open_workspace.root)

    await user.open("/")                       # noticing happens wherever you happen to be
    await user.open("/workspace")
    await user.should_see("Your project is not where it was")
    await user.should_see("I moved or renamed it")
    await user.should_see("I deleted it")
    assert CONTEXT.project is None

    user.find("I deleted it").click()
    await settle(user)
    assert CONTEXT.missing is None
    await user.open("/workspace")
    await user.should_see("Start a new project")


@pytest.mark.asyncio
async def test_settings_is_behind_the_gear_on_every_page(user: User, open_workspace):
    """Settings is the same everywhere and is not a place in the pipeline, so it is a drawer
    rather than the last tab in the row."""
    from transcript_toolkit.app.pages.common import NAV

    assert "/settings" not in [href for href, _ in NAV]
    await user.open("/step/clip")
    await user.should_see("Quit the toolkit")          # the drawer's content is on the page
    await user.should_see("Delete this project")
