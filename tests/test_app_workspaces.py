"""Opening, making and remembering workspaces; the API key; dropped-in transcripts."""
import json

import pytest

from transcript_toolkit.app import workspaces
from transcript_toolkit.errors import ToolkitError
from transcript_toolkit.project import init_project


@pytest.fixture(autouse=True)
def registry_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(workspaces, "support_dir", lambda: tmp_path / "support")


def test_creating_a_workspace_scaffolds_and_remembers_it(tmp_path):
    project = workspaces.create_workspace(tmp_path, "my-archive")
    assert project.config_path.exists() and project.data_dir.is_dir()
    assert [e["path"] for e in workspaces.load_registry()] == [str(project.root)]


def test_a_bad_name_is_refused_before_anything_is_written(tmp_path):
    for name in ("", "   ", "///", "..."):
        with pytest.raises(ToolkitError):
            workspaces.create_workspace(tmp_path, name)
    with pytest.raises(ToolkitError, match="no folder"):
        workspaces.create_workspace(tmp_path / "nope", "x")


def test_the_name_is_typed_and_the_folder_follows_from_it(tmp_path):
    """The whole point of the change: one name is entered, the other is derived. A project is
    never called `pilot2` in Finder and 'My Oral History Project' on screen."""
    from transcript_toolkit.core.config import project_name

    project = workspaces.create_workspace(tmp_path, "Anderson Family Oral History")
    assert project.root.name == "anderson-family-oral-history"
    assert project_name(project) == "Anderson Family Oral History"
    # and the page can say where it will land before anything is written
    assert workspaces.planned_folder(tmp_path, "Anderson Family Oral History") == project.root


def test_awkward_characters_in_a_name_still_make_a_sane_folder(tmp_path):
    """A name is a name — people put slashes, commas and capitals in them."""
    project = workspaces.create_workspace(tmp_path, "  Smith/Jones: Voices, 2026  ")
    assert project.root.name == "smith-jones-voices-2026"


def test_a_project_can_be_renamed_without_hand_editing_a_config_file(tmp_path):
    """Every project made before the name was derived is called the same thing. Renaming is
    the fix, and it must not be "open config.yaml in TextEdit"."""
    from transcript_toolkit.core.config import project_name

    project = workspaces.create_workspace(tmp_path, "Wrong Name")
    n_comments = sum(1 for ln in project.config_path.read_text().splitlines()
                     if ln.strip().startswith("#"))

    workspaces.rename_project(project, "OSF test")
    assert project_name(project) == "OSF test"
    assert workspaces.load_registry()[0]["name"] == "OSF test"      # the recent list too
    # config.yaml's comments ARE its documentation; a yaml round-trip would delete them
    assert sum(1 for ln in project.config_path.read_text().splitlines()
               if ln.strip().startswith("#")) == n_comments
    assert project.root.name == "wrong-name"                       # the folder is left alone


def test_renaming_only_touches_the_projects_own_name(tmp_path):
    """A `name:` belonging to some other section must not be the one that gets rewritten."""
    from transcript_toolkit.project import config_with_name

    text = ('project:\n  name: "Old"\n\n'
            'topics:\n  sets:\n    collection:\n      name: not-the-project\n')
    after = config_with_name(text, "New")
    assert 'name: "New"' in after and "name: not-the-project" in after
    assert "Old" not in after


def test_renaming_an_empty_name_is_refused(tmp_path):
    project = workspaces.create_workspace(tmp_path, "Keep This")
    with pytest.raises(ToolkitError):
        workspaces.rename_project(project, "   ")


def test_opening_a_plain_folder_fails_with_the_cli_wording(tmp_path):
    (tmp_path / "not-a-workspace").mkdir()
    with pytest.raises(ToolkitError, match="not a toolkit project folder"):
        workspaces.open_workspace(tmp_path / "not-a-workspace")


def test_most_recently_opened_comes_first(tmp_path):
    first = workspaces.create_workspace(tmp_path, "one")
    second = workspaces.create_workspace(tmp_path, "two")
    assert [e["path"] for e in workspaces.load_registry()] == [str(second.root), str(first.root)]
    workspaces.open_workspace(first.root)
    assert workspaces.load_registry()[0]["path"] == str(first.root)


def test_a_moved_folder_stays_listed_until_the_user_removes_it(tmp_path):
    """Never quietly drop someone's project from the list: show them what happened instead."""
    project = workspaces.create_workspace(tmp_path, "gone")
    import shutil
    shutil.rmtree(project.root)
    assert [e["path"] for e in workspaces.load_registry()] == [str(project.root)]
    workspaces.forget(str(project.root))
    assert workspaces.load_registry() == []


def test_an_unreadable_registry_says_so(tmp_path):
    workspaces.registry_path().parent.mkdir(parents=True, exist_ok=True)
    workspaces.registry_path().write_text("{ not json")
    with pytest.raises(ToolkitError, match="unreadable"):
        workspaces.load_registry()


def test_the_list_does_not_grow_without_bound(tmp_path):
    for i in range(workspaces.MAX_REMEMBERED + 4):
        workspaces.create_workspace(tmp_path, f"ws{i}")
    assert len(workspaces.load_registry()) == workspaces.MAX_REMEMBERED


# --- the key -------------------------------------------------------------------------------

def test_the_key_is_written_into_env_and_replaced_in_place(tmp_path):
    project = init_project(str(tmp_path / "ws"))
    assert not workspaces.has_api_key(project)

    workspaces.set_api_key(project, "sk-first")
    assert workspaces.has_api_key(project)
    workspaces.set_api_key(project, "sk-second")

    text = workspaces.env_path(project).read_text()
    assert text.count("OPENAI_API_KEY=") == 1 and "sk-second" in text and "sk-first" not in text
    # the scaffold's own comments are left alone
    assert "#" in text


def test_a_key_with_a_line_break_in_it_is_refused(tmp_path):
    project = init_project(str(tmp_path / "ws"))
    for bad in ("", "  ", "sk-abc def", "sk-abc\ndef"):
        with pytest.raises(ToolkitError):
            workspaces.set_api_key(project, bad)
    assert not workspaces.has_api_key(project)


def test_an_empty_key_setting_does_not_count_as_set(tmp_path):
    project = init_project(str(tmp_path / "ws"))
    workspaces.env_path(project).write_text("OPENAI_API_KEY=\n")
    assert not workspaces.has_api_key(project)


# --- transcripts ---------------------------------------------------------------------------

def test_transcripts_land_where_import_looks_for_them(tmp_path):
    project = init_project(str(tmp_path / "ws"))
    assert workspaces.transcript_count(project) == 0
    path = workspaces.add_transcript(project, "Some Person_SYNC.docx", b"pretend docx")
    assert path == project.data_dir / "Some Person_SYNC.docx"
    assert workspaces.transcript_count(project) == 1


def test_only_docx_is_accepted(tmp_path):
    project = init_project(str(tmp_path / "ws"))
    with pytest.raises(ToolkitError, match="not a .docx"):
        workspaces.add_transcript(project, "notes.pdf", b"x")


def test_a_path_in_the_upload_name_cannot_escape_the_data_folder(tmp_path):
    project = init_project(str(tmp_path / "ws"))
    path = workspaces.add_transcript(project, "../../evil.docx", b"x")
    assert path.parent == project.data_dir


def test_the_registry_file_is_plain_readable_json(tmp_path):
    workspaces.create_workspace(tmp_path, "ws")
    entries = json.loads(workspaces.registry_path().read_text())
    assert set(entries[0]) == {"path", "name", "opened"}
