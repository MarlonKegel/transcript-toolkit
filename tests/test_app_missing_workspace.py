"""What happens when the open project folder is renamed, moved or thrown away.

It is Finder: nobody there knows the app has the folder open, and both renaming it and
deleting it are ordinary things to do. Every page then reads files that are not there — which
is how a settings page became a 500 with a raw FileNotFoundError on it.
"""
import shutil

import pytest

from transcript_toolkit.app import jobs, workspaces
from transcript_toolkit.app.context import AppContext
from transcript_toolkit.core.config import load_root_config, project_name
from transcript_toolkit.errors import ToolkitError
from transcript_toolkit.project import find_project, init_project


@pytest.fixture(autouse=True)
def registry_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(workspaces, "support_dir", lambda: tmp_path / "support")


def test_a_vanished_folder_closes_the_project_instead_of_breaking_pages(tmp_path):
    project = init_project(str(tmp_path / "ws"))
    context = AppContext()
    context.open(project)

    shutil.rmtree(project.root)
    assert context.check_still_there() == project.root
    assert context.project is None                 # nothing left for a page to read
    assert context.missing == project.root         # but the page can say what happened


def test_a_project_that_is_still_there_is_left_alone(tmp_path):
    project = init_project(str(tmp_path / "ws"))
    context = AppContext()
    context.open(project)
    assert context.check_still_there() is None
    assert context.project is project


def test_the_last_runs_output_goes_with_it(tmp_path):
    """Output from a project that no longer exists must not sit under the next one."""
    project = init_project(str(tmp_path / "ws"))
    context = AppContext()
    context.open(project)
    context.jobs.current = jobs.Job(id=1, title="Clip — demo", command="toolkit clip --demo",
                                    workspace=project.root, started_at=0.0)
    context.jobs.current.state = jobs.SUCCEEDED

    shutil.rmtree(project.root)
    context.check_still_there()
    assert context.jobs.current is None


def test_a_renamed_folder_can_be_pointed_at_again(tmp_path):
    """"I moved or renamed it" — the project is intact, only its path changed."""
    project = init_project(str(tmp_path / "ws"))
    (project.data_dir / "Person_SYNC.docx").write_text("x")
    moved = tmp_path / "somewhere-else"
    project.root.rename(moved)

    context = AppContext()
    context.open(project)
    assert context.check_still_there() == project.root

    context.open(workspaces.open_workspace(moved))
    assert context.project.root == moved
    assert (context.project.data_dir / "Person_SYNC.docx").exists()


# --- the messages ----------------------------------------------------------------------------

def test_a_missing_folder_says_so_rather_than_naming_a_config_file(tmp_path):
    """"Missing config file: .../config.yaml" describes a symptom of a folder that is gone."""
    project = init_project(str(tmp_path / "ws"))
    shutil.rmtree(project.root)
    with pytest.raises(ToolkitError, match="project folder is not there"):
        load_root_config(project)
    with pytest.raises(ToolkitError, match="project folder is not there"):
        project_name(project)


def test_opening_a_path_with_nothing_at_it_says_that(tmp_path):
    with pytest.raises(ToolkitError, match="There is no folder at"):
        find_project(explicit=str(tmp_path / "never-existed"))


def test_opening_the_folder_above_a_project_says_which_folder_to_pick(tmp_path):
    """The commonest miss with a folder picker: choosing the parent."""
    init_project(str(tmp_path / "ws"))
    with pytest.raises(ToolkitError, match="Open the project folder itself"):
        find_project(explicit=str(tmp_path))


# --- deleting one ------------------------------------------------------------------------------

def test_deleting_takes_the_folder_and_forgets_it(tmp_path, monkeypatch):
    monkeypatch.setattr(workspaces.sys, "platform", "linux")     # no Trash to move it to
    project = workspaces.create_workspace(tmp_path, "Going Away")
    assert workspaces.load_registry()

    workspaces.delete_project(project)
    assert not project.root.exists()
    assert workspaces.load_registry() == []


def test_deleting_on_a_mac_goes_to_the_trash_so_it_can_be_undone(tmp_path, monkeypatch):
    """A wrong answer to the confirmation should be recoverable, not final."""
    calls = []
    monkeypatch.setattr(workspaces.sys, "platform", "darwin")
    project = workspaces.create_workspace(tmp_path, "Going Away")

    class Result:
        returncode = 0
        stdout = stderr = ""

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return Result()

    import subprocess
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert workspaces.delete_project(project) == "the Trash"
    assert calls and calls[0][0] == "osascript"
    assert str(project.root) in calls[0][-1]
    assert project.root.exists()            # Finder would have moved it; nothing else may


def test_a_folder_that_is_not_a_project_is_never_deleted(tmp_path):
    from transcript_toolkit.project import Project

    plain = tmp_path / "someones-documents"
    plain.mkdir()
    (plain / "important.docx").write_text("x")
    with pytest.raises(ToolkitError, match="not a toolkit project folder"):
        workspaces.delete_project(Project(plain))
    assert (plain / "important.docx").exists()


def test_what_will_be_lost_is_counted_before_asking(tmp_path):
    project = workspaces.create_workspace(tmp_path, "Full One")
    (project.data_dir / "a.docx").write_text("x")
    (project.data_dir / "b.docx").write_text("x")
    (project.outputs_dir / "clips").mkdir(parents=True)
    (project.outputs_dir / "clips" / "clips.parquet").write_text("x")

    counts = workspaces.describe(project)
    assert counts["transcripts"] == 2 and counts["results"] == 1
