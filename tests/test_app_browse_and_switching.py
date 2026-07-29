"""Finding a folder without typing its path, and changing which project is open."""
import pytest

from transcript_toolkit.app import jobs
from transcript_toolkit.app.context import AppContext
from transcript_toolkit.app.pages import browse
from transcript_toolkit.errors import ToolkitError
from transcript_toolkit.project import init_project


# --- the folder browser ------------------------------------------------------------------------

def test_only_folders_are_offered_and_hidden_ones_are_not(tmp_path):
    (tmp_path / "Projects").mkdir()
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "notes.txt").write_text("x")
    assert [p.name for p in browse.subfolders(tmp_path)] == ["Projects"]


def test_a_folder_it_cannot_read_is_empty_rather_than_an_error(tmp_path):
    """Somebody's Mac will have a folder the app cannot open. Browsing past it is not a crash."""
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o000)
    try:
        assert browse.subfolders(locked) == []
    finally:
        locked.chmod(0o755)


def test_existing_projects_are_marked_so_you_can_see_which_folder_to_pick(tmp_path):
    project = init_project(str(tmp_path / "an-archive"))
    (tmp_path / "just-a-folder").mkdir()
    assert browse.is_workspace(project.root)
    assert not browse.is_workspace(tmp_path / "just-a-folder")


def test_the_shortcuts_are_this_users_own_folders(monkeypatch, tmp_path):
    """The path shown to somebody must be theirs, not the one baked in on a developer's box."""
    home = tmp_path / "someone"
    (home / "Documents").mkdir(parents=True)
    monkeypatch.setattr(browse.Path, "home", staticmethod(lambda: home))
    places = dict(browse.shortcuts())
    assert places["Home"] == home and places["Documents"] == home / "Documents"


def test_the_suggested_place_for_a_new_project_is_this_users_documents(monkeypatch, tmp_path):
    from transcript_toolkit.app import workspaces

    home = tmp_path / "someone"
    (home / "Documents").mkdir(parents=True)
    monkeypatch.setattr(workspaces.Path, "home", staticmethod(lambda: home))
    assert workspaces.suggested_parent() == home / "Documents"


# --- changing project --------------------------------------------------------------------------

def test_opening_another_project_clears_the_last_ones_output(tmp_path):
    """The terminal panel showed the previous project's run under the new project's name."""
    first = init_project(str(tmp_path / "first"))
    second = init_project(str(tmp_path / "second"))
    context = AppContext()
    context.open(first)
    context.jobs.current = jobs.Job(id=1, title="Clip — demo", command="toolkit clip --demo",
                                    workspace=first.root, started_at=0.0)
    context.jobs.current.state = jobs.SUCCEEDED

    context.open(second)
    assert context.jobs.current is None


def test_reopening_the_same_project_leaves_its_run_alone(tmp_path):
    project = init_project(str(tmp_path / "ws"))
    context = AppContext()
    context.open(project)
    context.jobs.current = jobs.Job(id=1, title="Clip — demo", command="toolkit clip --demo",
                                    workspace=project.root, started_at=0.0)
    context.jobs.current.state = jobs.SUCCEEDED

    context.open(project)
    assert context.jobs.current is not None


def test_switching_away_from_a_live_run_is_refused(tmp_path, monkeypatch):
    """Switching would orphan it: the server holds the running command's terminal."""
    first = init_project(str(tmp_path / "first"))
    second = init_project(str(tmp_path / "second"))
    context = AppContext()
    context.open(first)
    context.jobs.current = jobs.Job(id=1, title="Label — full run", command="toolkit label",
                                    workspace=first.root, started_at=0.0)
    monkeypatch.setattr(type(context.jobs), "busy", property(lambda self: True))

    with pytest.raises(ToolkitError, match="Label — full run"):
        context.open(second)
    assert context.project is first
