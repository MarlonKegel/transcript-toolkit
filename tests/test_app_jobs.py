"""Running commands for the app: output, the confirmation prompt, stopping, and failure.

The prompt tests drive the toolkit's *real* `choose_transport` through a real terminal, so
they prove the app can read and answer the actual question a full run asks — not a copy of it.
"""
import asyncio
import shutil
import sys
from pathlib import Path

import pytest

from transcript_toolkit.app import jobs
from transcript_toolkit.errors import ToolkitError

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def stub_child(monkeypatch):
    """Point jobs at `python -c`, so a test's argv is the program the job runs."""
    monkeypatch.setattr(jobs, "CHILD_COMMAND", [sys.executable, "-u", "-c"])


async def finish(job, timeout=20.0):
    async with asyncio.timeout(timeout):
        while job.live:
            await asyncio.sleep(0.02)
    return job


async def reaches(job, state, timeout=20.0):
    async with asyncio.timeout(timeout):
        while job.state != state:
            await asyncio.sleep(0.02)
    return job


@pytest.mark.asyncio
async def test_output_is_captured_in_order(stub_child, tmp_path):
    manager = jobs.JobManager()
    job = await manager.start("t", ["print('one'); print('two')"], tmp_path, with_project=False)
    await finish(job)
    assert job.state == jobs.SUCCEEDED
    assert list(job.lines) == ["one", "two"]
    assert job.returncode == 0


@pytest.mark.asyncio
async def test_the_real_spend_prompt_is_recognised_and_answerable(stub_child, tmp_path):
    """The whole reason jobs use a terminal: the CLI asks its own question, with its own
    figures, and the app answers it."""
    manager = jobs.JobManager()
    job = await manager.start("t", [
        "from transcript_toolkit.core.console import choose_transport;"
        "print('picked', choose_transport('Label 3 interviews.', (2.0, 1.0)))"
    ], tmp_path, with_project=False)

    await reaches(job, jobs.WAITING)
    assert job.prompt.endswith("Choose [1/2/n] ")
    assert [a.label for a in job.answers()] == ["Run now", "Use the Batch API", "Cancel"]
    # the figures on screen are the CLI's own
    assert any("~$2.00" in line for line in job.lines)
    assert any("~$1.00" in line for line in job.lines)

    manager.answer("2")                       # the Batch API
    await finish(job)
    assert any("picked True" in line for line in job.lines)


@pytest.mark.asyncio
async def test_cancelling_at_the_prompt_is_not_a_failure(stub_child, tmp_path):
    manager = jobs.JobManager()
    job = await manager.start("t", [
        "import sys\n"
        "from transcript_toolkit.core.console import choose_transport\n"
        "from transcript_toolkit.errors import ToolkitError\n"
        "try:\n"
        "    choose_transport('Label 3 interviews.', (2.0, 1.0))\n"
        "except ToolkitError as e:\n"
        "    print(f'error: {e}', file=sys.stderr); sys.exit(2)\n"
    ], tmp_path, with_project=False)
    await reaches(job, jobs.WAITING)
    manager.answer("n")
    await finish(job)
    # The CLI reports a decline the same way it reports a problem; the app must not.
    assert job.state == jobs.CANCELLED and job.error == ""


@pytest.mark.asyncio
async def test_stopping_is_a_ctrl_c(stub_child, tmp_path):
    manager = jobs.JobManager()
    job = await manager.start("t", [
        "import time, sys\n"
        "print('working')\n"
        "try:\n"
        "    time.sleep(30)\n"
        "except KeyboardInterrupt:\n"
        "    print('interrupted'); sys.exit(130)\n"
    ], tmp_path, with_project=False)
    while "working" not in job.lines:
        await asyncio.sleep(0.02)

    await manager.stop()
    await finish(job)
    assert job.state == jobs.STOPPED
    assert "interrupted" in job.lines


@pytest.mark.asyncio
async def test_a_toolkit_error_is_kept_whole(stub_child, tmp_path):
    manager = jobs.JobManager()
    job = await manager.start("t", [
        "import sys; print('starting');"
        "print('error: line one\\nline two', file=sys.stderr); sys.exit(2)"
    ], tmp_path, with_project=False)
    await finish(job)
    assert job.state == jobs.FAILED
    assert job.error == "line one\nline two"


@pytest.mark.asyncio
async def test_an_unexpected_crash_still_ends_the_job(stub_child, tmp_path):
    manager = jobs.JobManager()
    job = await manager.start("t", ["raise SystemExit(9)"], tmp_path, with_project=False)
    await finish(job)
    assert job.state == jobs.FAILED and job.returncode == 9 and job.error == ""


@pytest.mark.asyncio
async def test_only_one_job_at_a_time(stub_child, tmp_path):
    manager = jobs.JobManager()
    job = await manager.start("first", ["import time; time.sleep(5)"], tmp_path,
                              with_project=False)
    with pytest.raises(ToolkitError, match="still running"):
        await manager.start("second", ["print('no')"], tmp_path, with_project=False)
    await manager.stop()
    await finish(job)
    # and once it is done the slot is free again
    second = await manager.start("second", ["print('yes')"], tmp_path, with_project=False)
    await finish(second)
    assert second.state == jobs.SUCCEEDED


@pytest.mark.asyncio
async def test_answering_when_nothing_is_waiting_is_refused(stub_child, tmp_path):
    manager = jobs.JobManager()
    with pytest.raises(ToolkitError):
        manager.answer("y")
    with pytest.raises(ToolkitError, match="Nothing is running"):
        await manager.stop()


@pytest.mark.asyncio
async def test_a_run_that_cannot_start_does_not_block_every_later_one(stub_child, tmp_path):
    """If the workspace folder has gone, spawning fails. Without clearing the slot the app
    would answer "still running" for the rest of the session."""
    manager = jobs.JobManager()
    with pytest.raises(ToolkitError, match="Could not start"):
        await manager.start("t", ["print(1)"], tmp_path / "not-there", with_project=False)
    assert not manager.busy

    job = await manager.start("t", ["print('fine')"], tmp_path, with_project=False)
    await finish(job)
    assert job.state == jobs.SUCCEEDED


def test_nothing_new_means_nothing_to_redraw():
    """A page redraws for things that add no output — a question arriving, the run ending. If
    `since` answered those with the whole buffer, the run would be printed again beneath
    itself."""
    job = jobs.Job(id=1, title="t", command="c", workspace=Path("/tmp"), started_at=0.0)
    job.add_line("one")
    job.add_line("two")
    assert job.since(0) == ["one", "two"]
    assert job.since(job.emitted) == []
    assert job.since(job.emitted + 5) == []


def test_new_lines_survive_the_buffer_filling_up():
    """A page catches up by counting lines ever written, because a long run drops its oldest
    ones — counting the buffer's length would silently stop updating."""
    job = jobs.Job(id=1, title="t", command="c", workspace=Path("/tmp"), started_at=0.0)
    for i in range(jobs.MAX_LOG_LINES + 50):
        job.add_line(str(i))
    assert job.emitted == jobs.MAX_LOG_LINES + 50
    assert len(job.lines) == jobs.MAX_LOG_LINES
    assert job.since(job.emitted - 3) == [str(job.emitted - 3), str(job.emitted - 2),
                                          str(job.emitted - 1)]
    assert job.since(0) == list(job.lines)          # a fresh page gets everything still held


# --- against the real CLI -------------------------------------------------------------------

@pytest.fixture
def workspace(tmp_path):
    from transcript_toolkit.project import init_project
    from transcript_toolkit.steps.import_ import run_import

    project = init_project(str(tmp_path / "ws"))
    for docx in FIXTURES.glob("*.docx"):
        shutil.copy(docx, project.data_dir)
    run_import(project)
    return project


@pytest.mark.asyncio
async def test_a_real_command_runs_in_the_workspace(workspace):
    manager = jobs.JobManager()
    job = await manager.start("Status", ["status"], workspace.root)
    await finish(job, timeout=60)
    assert job.state == jobs.SUCCEEDED
    assert any(str(workspace.root) in line for line in job.lines)
    assert job.command == "toolkit status"          # what the user is shown, without --project


@pytest.mark.asyncio
async def test_the_demo_gate_refusal_arrives_as_an_offer_to_fix_it(workspace):
    """A full run with no demo behind it: the CLI refuses, and the app can turn that refusal
    into the button that fixes it."""
    from transcript_toolkit.app import content

    manager = jobs.JobManager()
    argv = content.run_argv(content.BY_SLUG["clip"], demo=False)
    job = await manager.start("Clip", argv, workspace.root)
    await finish(job, timeout=60)
    assert job.state == jobs.FAILED
    assert content.fix_for(job.error) == "demo"
