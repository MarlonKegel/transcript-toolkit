import pytest

from transcript_toolkit.errors import ToolkitError
from transcript_toolkit.project import (display_name, find_project, folder_name, init_project,
                                        reset_prompt)


# --- the project's two names -----------------------------------------------------------------
#
# One is typed and the other follows. A project called "My Oral History Project" in a folder
# called `pilot2` is what made the app show a name nobody had ever entered.

@pytest.mark.parametrize("name, folder", [
    ("Anderson Family Oral History", "anderson-family-oral-history"),
    ("  Smith/Jones: Voices, 2026  ", "smith-jones-voices-2026"),
    ("My Oral History Project", "my-oral-history-project"),
    ("OSF", "osf"),
    ("a" * 3, "aaa"),
])
def test_a_name_becomes_a_folder_you_could_type(name, folder):
    assert folder_name(name) == folder


@pytest.mark.parametrize("bad", ["", "   ", "///", "...", "-", "!!!"])
def test_a_name_with_nothing_in_it_is_refused(bad):
    with pytest.raises(ToolkitError, match="no letters or numbers"):
        folder_name(bad)


@pytest.mark.parametrize("folder", ["my-archive", "anderson-family-oral-history", "osf"])
def test_a_folder_name_survives_the_round_trip(folder):
    assert folder_name(display_name(folder)) == folder


def test_init_writes_the_name_into_the_config(tmp_path):
    from transcript_toolkit.core.config import project_name

    given = init_project(str(tmp_path / "anywhere"), name="Anderson Family Oral History")
    assert project_name(given) == "Anderson Family Oral History"

    # no name given: it comes from the folder, so the two still agree
    derived = init_project(str(tmp_path / "my-archive"))
    assert project_name(derived) == "My Archive"


def test_init_creates_workspace(tmp_path):
    project = init_project(str(tmp_path / "ws"))
    assert project.marker_path.exists()
    assert project.config_path.exists()
    for step in ("import", "clip", "label", "summarize", "topics", "locations", "export"):
        assert (project.advanced_dir / f"{step}.yaml").exists(), step
    for d in (project.data_dir, project.outputs_dir, project.diags_dir, project.prompts_dir,
              project.topics_dir, project.locations_dir, project.cache_dir):
        assert d.is_dir()
    assert (project.root / ".env").exists()
    assert (project.root / ".gitignore").exists()
    assert (project.root / "AGENTS.md").exists()
    assert (project.topics_dir / "example_topics.csv").exists()


def test_init_refuses_nonempty(tmp_path):
    (tmp_path / "stuff.txt").write_text("hi")
    with pytest.raises(ToolkitError, match="not empty"):
        init_project(str(tmp_path))


def test_init_refuses_double(tmp_path):
    init_project(str(tmp_path / "ws"))
    with pytest.raises(ToolkitError, match="already"):
        init_project(str(tmp_path / "ws"))


def test_find_project_walks_up(tmp_path):
    project = init_project(str(tmp_path / "ws"))
    nested = project.data_dir / "deep" / "er"
    nested.mkdir(parents=True)
    found = find_project(start=nested)
    assert found.root == project.root


def test_find_project_explicit_and_failure(tmp_path):
    project = init_project(str(tmp_path / "ws"))
    assert find_project(explicit=str(project.root)).root == project.root
    with pytest.raises(ToolkitError, match="not a toolkit workspace"):
        find_project(explicit=str(tmp_path))
    with pytest.raises(ToolkitError, match="Not inside a toolkit workspace"):
        find_project(start=tmp_path / "elsewhere")


def test_reset_prompt_unknown_name(tmp_path):
    project = init_project(str(tmp_path / "ws"))
    with pytest.raises(ToolkitError, match="No default prompt"):
        reset_prompt(project, "nope.md")


def test_reset_prompt_handles_subfolders_and_old_names(tmp_path):
    """Prompt addendums live in prompts/prompt_addendums/, and prompts renamed after workspaces
    already existed keep working under their old names."""
    from transcript_toolkit.project import reset_prompt
    project = init_project(str(tmp_path / "ws"))

    addendum = project.prompts_dir / "prompt_addendums" / "justify_topics.md"
    assert addendum.exists()                                  # scaffolded recursively
    addendum.write_text("edited")
    assert reset_prompt(project, "prompt_addendums/justify_topics.md") == addendum
    assert addendum.read_text() != "edited"

    # old names still resolve to their new locations
    assert reset_prompt(project, "justify_topics.md") == addendum
    assert reset_prompt(project, "segment_interview.md").name == "clip_interview.md"


def test_reset_prompt_unknown_name_lists_available(tmp_path):
    from transcript_toolkit.project import reset_prompt
    project = init_project(str(tmp_path / "ws"))
    with pytest.raises(ToolkitError, match="prompt_addendums/justify_topics.md"):
        reset_prompt(project, "nope.md")


def test_no_claude_md_in_workspace(tmp_path):
    project = init_project(str(tmp_path / "ws"))
    assert (project.root / "AGENTS.md").exists()
    assert not (project.root / "CLAUDE.md").exists()
