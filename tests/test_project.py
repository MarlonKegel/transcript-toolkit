import pytest

from transcript_toolkit.errors import ToolkitError
from transcript_toolkit.project import find_project, init_project, reset_prompt


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
