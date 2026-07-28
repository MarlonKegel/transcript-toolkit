"""Clicking things.

The pages render correctly (test_app_pages.py) and the runner works (test_app_jobs.py); this
is the join between them — that a button really starts the command it names, and that the run
panel then shows it.
"""
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
    user.find("Run on the whole corpus").click()
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
