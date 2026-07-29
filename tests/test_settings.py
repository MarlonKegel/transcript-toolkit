"""Settings read and written the way the app does it.

config.yaml is the project's own file: somebody may have it open in TextEdit, and its comments are
the documentation of every setting. So the app has to change one line and leave the rest of the
file alone, and it has to read its explanations out of those comments rather than carry a second
copy of them.
"""
import pytest
import yaml

from transcript_toolkit.core import settings
from transcript_toolkit.errors import ToolkitError
from transcript_toolkit.project import init_project


@pytest.fixture
def project(tmp_path):
    return init_project(str(tmp_path / "ws"))


# --- reading the explanations out of the file ------------------------------------------------

def test_every_setting_the_app_offers_is_documented_in_the_scaffold(project):
    """The app shows config.yaml's own comment beside each control. A blessed setting with no
    comment would appear in the app as a bare box with no explanation at all."""
    said = settings.explanations(project.config_path.read_text())
    for field in settings.FIELDS:
        assert field.path in said, f"{field.path} has no comment in the scaffold config.yaml"
        assert said[field.path].strip(), field.path


def test_a_project_made_before_a_comment_existed_still_gets_the_explanation(project):
    """Marlon's own test project was created by an earlier version, whose config.yaml documented
    only some of the blessed settings. The shipped file is the same file, so its wording fills the
    gaps — and a comment the project has reworded still wins."""
    project.config_path.write_text(
        "clip:\n  model: gpt-5.6-sol\n  # Our own words about this one.\n  reasoning: medium\n")
    said = settings.explanations_for(project)
    assert said["clip.model"] == settings.shipped_explanations()["clip.model"]
    assert said["clip.reasoning"] == "Our own words about this one."


def test_every_setting_has_something_to_say_about_it_in_any_project(project):
    project.config_path.write_text("clip:\n  model: gpt-5.6-sol\n")
    said = settings.explanations_for(project)
    for field in settings.FIELDS:
        assert said.get(field.path, "").strip(), field.path


def test_the_explanation_is_the_comment_above_the_setting_and_the_one_beside_it():
    said = settings.explanations("""\
step:
  # What this does.
  # A second line about it.
  thing: 3                # e.g. 4
""")
    assert said["step.thing"] == "What this does.\nA second line about it.\ne.g. 4"


def test_a_banner_at_the_top_of_the_file_is_not_read_as_a_setting_explanation():
    """The file opens with a paragraph about the file. A blank line separates it from the first
    setting, and that is what keeps it from being attributed to it."""
    said = settings.explanations("""\
# About this whole file.

project:
  name: x
""")
    assert "project" not in said and "project.name" not in said


def test_a_section_banner_loses_its_rules():
    said = settings.explanations("# --- clip: split interviews up ------\nclip:\n  model: a\n")
    assert said["clip"] == "clip: split interviews up"


def test_a_hash_inside_a_value_is_not_a_comment():
    said = settings.explanations('step:\n  thing: "a # b"     # the real comment\n')
    assert said["step.thing"] == "the real comment"


# --- writing one setting without touching anything else -------------------------------------

EVERY_KIND = [
    ("clip.model", "gpt-5.4-nano"),
    ("clip.reasoning", "high"),
    ("summarize.pool_sessions", False),
    ("import.interviewer_labels", ["Q", "Q1", "Q2"]),
    ("import.other_labels", []),
    ("locations.rollup.thresholds", [5, 7.5, 10]),
    ("locations.relabel", {"Czech Republic": "Czechia"}),
    ("locations.place_tags", ["Chechnya", "Crimea"]),
    ("label.addendum", "prompt_addendums/label_addendum.md"),
    ("label.addendum", None),
    ("export.locations", "countries"),
    ("project.name", "A Project: With Punctuation"),
]


@pytest.mark.parametrize("path,value", EVERY_KIND, ids=[f"{p}={v!r}"[:40] for p, v in EVERY_KIND])
def test_a_setting_changes_and_every_comment_survives(project, path, value):
    before = project.config_path.read_text()
    settings.save(project, {path: value})
    after = project.config_path.read_text()

    assert settings.value_at(yaml.safe_load(after), path) == value
    for line in before.splitlines():
        if line.strip().startswith("#"):
            assert line in after, f"lost a comment line: {line}"


def test_nothing_else_in_the_file_changes(project):
    before = yaml.safe_load(project.config_path.read_text())
    settings.save(project, {"clip.model": "gpt-5.4-nano"})
    after = yaml.safe_load(project.config_path.read_text())

    before["clip"]["model"] = "gpt-5.4-nano"
    assert after == before


def test_several_settings_save_together(project):
    settings.save(project, {"clip.model": "gpt-5.4-nano", "clip.reasoning": "low",
                            "summarize.pool_sessions": False})
    loaded = yaml.safe_load(project.config_path.read_text())
    assert loaded["clip"] == {"model": "gpt-5.4-nano", "reasoning": "low"}
    assert loaded["summarize"]["pool_sessions"] is False


def test_a_setting_that_is_not_in_the_file_yet_is_added(project):
    text = "clip:\n  model: a\n"
    project.config_path.write_text(text)
    settings.save(project, {"clip.reasoning": "high"})
    assert yaml.safe_load(project.config_path.read_text()) == {
        "clip": {"model": "a", "reasoning": "high"}}


def test_a_whole_missing_section_is_added(project):
    project.config_path.write_text("clip:\n  model: a\n")
    settings.save(project, {"locations.rollup.thresholds": [10, 20]})
    assert yaml.safe_load(project.config_path.read_text()) == {
        "clip": {"model": "a"}, "locations": {"rollup": {"thresholds": [10, 20]}}}


def test_a_trailing_comment_stays_on_its_own_line(project):
    project.config_path.write_text("clip:\n  reasoning: medium    # none | low | medium\n")
    settings.save(project, {"clip.reasoning": "xhigh"})
    line = project.config_path.read_text().splitlines()[1]
    assert line.startswith("  reasoning: xhigh")
    assert line.endswith("# none | low | medium")


def test_replacing_a_block_with_one_line_removes_the_block(project):
    project.config_path.write_text("locations:\n  rollup:\n    thresholds: [1, 2]\n  relabel: {}\n")
    settings.save(project, {"locations.rollup": {"scheme": "flat"}})
    assert yaml.safe_load(project.config_path.read_text()) == {
        "locations": {"rollup": {"scheme": "flat"}, "relabel": {}}}


def test_a_topic_lists_rollup_can_be_rewritten(project):
    """`sets` is written by the toolkit when a topic list is first used, on one line per key —
    which the app then has to be able to change."""
    project.config_path.write_text(
        "topics:\n  sets:\n    main:\n      file: topics/main.csv\n"
        "      rollup: { scheme: flat, threshold_pct: 30 }\n")
    settings.save(project, {"topics.sets.main.rollup": {"scheme": "binned",
                                                       "thresholds": [10, 12.5]}})
    loaded = yaml.safe_load(project.config_path.read_text())
    assert loaded["topics"]["sets"]["main"] == {
        "file": "topics/main.csv",
        "rollup": {"scheme": "binned", "thresholds": [10, 12.5]}}


def test_a_file_that_has_been_rearranged_by_hand_is_left_alone(project):
    """Somebody who reformatted their own config.yaml keeps it, and is told where to make the
    change themselves, rather than having the app write a second copy of the setting."""
    project.config_path.write_text("clip:\n    model: a\n")       # four-space indent
    with pytest.raises(ToolkitError, match="Change them in the file itself"):
        settings.save(project, {"clip.model": "b"})
    assert project.config_path.read_text() == "clip:\n    model: a\n"


def test_saving_nothing_changes_nothing(project):
    before = project.config_path.read_text()
    settings.save(project, {})
    assert project.config_path.read_text() == before


# --- what the app puts in front of each setting ---------------------------------------------

def test_models_offered_are_models_the_toolkit_can_price(project):
    """A model with no price cannot be costed, and every run asks what it will cost before it
    spends anything."""
    from transcript_toolkit.core.cost import pricing

    field = settings.BY_PATH["clip.model"]
    assert set(settings.choices_for(field)) == set(pricing())
    scaffold = yaml.safe_load(project.config_path.read_text())
    for step in ("clip", "label", "summarize", "topics", "locations"):
        assert scaffold[step]["model"] in pricing(), step


def test_export_modes_offered_are_the_exporters_own(project):
    from transcript_toolkit.steps.export import LOCATION_MODES

    field = settings.BY_PATH["export.locations"]
    assert list(settings.choices_for(field)) == list(LOCATION_MODES)


def test_reasoning_levels_offered_are_the_ones_the_api_call_accepts():
    from transcript_toolkit.core.llm import REASONING_LEVELS, check_levels

    field = settings.BY_PATH["clip.reasoning"]
    assert settings.choices_for(field) == REASONING_LEVELS
    for level in settings.choices_for(field):
        check_levels(level, "low")          # raises if the level is not one the call accepts


def test_every_step_page_has_something_to_show(project):
    """A step page draws `for_step`; an empty list would give it an empty settings section."""
    for step in ("clip", "label", "summarize", "topics", "locations", "export", "import"):
        assert settings.for_step(step), step
    assert settings.for_step(settings.PROJECT)
