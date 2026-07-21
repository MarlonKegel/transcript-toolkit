import pytest

from transcript_toolkit.core.config import load_step_config, project_name, require
from transcript_toolkit.errors import ToolkitError
from transcript_toolkit.project import init_project


@pytest.fixture
def project(tmp_path):
    return init_project(str(tmp_path / "ws"))


def test_scaffold_configs_load_for_every_step(project):
    for step in ("import", "clip", "label", "summarize", "topics", "locations", "export"):
        cfg = load_step_config(project, step)
        assert isinstance(cfg, dict) and cfg, step


def test_root_section_wins_over_advanced(project):
    # scaffold: clip.model in root, verbosity in advanced
    cfg = load_step_config(project, "clip")
    assert cfg["model"] == "gpt-5.5"
    assert cfg["verbosity"] == "low"
    # user overrides verbosity in the root section -> root wins
    project.config_path.write_text(
        project.config_path.read_text().replace(
            "clip:\n  model: gpt-5.5", "clip:\n  verbosity: high\n  model: gpt-5.5"))
    assert load_step_config(project, "clip")["verbosity"] == "high"


def test_missing_advanced_file_fails_loud(project):
    (project.advanced_dir / "clip.yaml").unlink()
    with pytest.raises(ToolkitError, match="Missing config file"):
        load_step_config(project, "clip")


def test_unparseable_yaml_fails_loud(project):
    project.config_path.write_text("clip: [unclosed")
    with pytest.raises(ToolkitError, match="Could not parse"):
        load_step_config(project, "clip")


def test_require_reports_missing_keys(project):
    with pytest.raises(ToolkitError, match="model, reasoning"):
        require({"model": None}, ["model", "reasoning"], "clip")


def test_project_name_from_config(project):
    assert project_name(project) == "My Oral History Project"
