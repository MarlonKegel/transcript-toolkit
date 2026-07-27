import pytest
from openpyxl import Workbook

from transcript_toolkit.errors import ToolkitError
from transcript_toolkit.project import init_project
from transcript_toolkit.steps.topics.taxonomy import build_legend, load_topic_set


@pytest.fixture
def project(tmp_path):
    return init_project(str(tmp_path / "ws"))


def cfg_for(file):
    return {"sets": {"main": {"file": file}}}


def write_csv(project, text, name="topics/main.csv"):
    (project.root / name).write_text(text)


CSV = ('id,name,description\n'
       'education,Education,"Schooling of any kind."\n'
       ',Career and Work,"Jobs and workplaces."\n')

GOLDEN_TAXONOMY = ("## Education\n\nSchooling of any kind.\n\n"
                   "## Career and Work\n\nJobs and workplaces.")


def test_csv_happy_path(project):
    write_csv(project, CSV)
    tset = load_topic_set(project, cfg_for("topics/main.csv"), "main")
    assert tset.name == "main"
    assert tset.ids == ["education", "career_and_work"]        # explicit id + slugged name
    assert tset.topics == [{"id": "education", "name": "Education"},
                           {"id": "career_and_work", "name": "Career and Work"}]
    assert tset.source == project.root / "topics" / "main.csv"


def test_taxonomy_text_byte_stable_golden(project):
    write_csv(project, CSV)
    tset = load_topic_set(project, cfg_for("topics/main.csv"), "main")
    # BYTE-STABILITY GOLDEN: this text feeds cache keys and demo fingerprints — if this fails,
    # the generated format changed and every user's cache/demo would go stale.
    assert tset.taxonomy_text == GOLDEN_TAXONOMY


def test_legend_byte_stable_golden(project):
    write_csv(project, CSV)
    tset = load_topic_set(project, cfg_for("topics/main.csv"), "main")
    assert build_legend(tset.topics) == (
        "## Topics\n\n"
        "Score the clip against each of these topics, using exactly these ids in your output. "
        "Definitions follow below.\n\n"
        "- `education` — Education\n"
        "- `career_and_work` — Career and Work")


def test_xlsx_happy_path(project):
    wb = Workbook()
    ws = wb.active
    ws.append(["name", "description"])
    ws.append(["Education", "Schooling of any kind."])
    ws.append(["Career and Work", "Jobs and workplaces."])
    ws.append([None, None])                                    # trailing blank row is skipped
    wb.save(project.root / "topics" / "main.xlsx")
    tset = load_topic_set(project, cfg_for("topics/main.xlsx"), "main")
    assert tset.ids == ["education", "career_and_work"]
    assert tset.taxonomy_text == GOLDEN_TAXONOMY               # identical across csv and xlsx


def test_slugging(project):
    write_csv(project, 'name,description\n"Community & Belonging! (2024)","Ties."\n')
    tset = load_topic_set(project, cfg_for("topics/main.csv"), "main")
    assert tset.ids == ["community_belonging_2024"]


def test_duplicate_ids_fail_with_row_numbers(project):
    write_csv(project, 'name,description\n"Health, Care","A."\n"Health & Care","B."\n')
    with pytest.raises(ToolkitError, match=r"row 3.*duplicate topic id.*row 2"):
        load_topic_set(project, cfg_for("topics/main.csv"), "main")


def test_missing_description_fails_with_row_number(project):
    write_csv(project, 'name,description\nEducation,"Fine."\nCareer,\n')
    with pytest.raises(ToolkitError, match=r"row 3.*empty description"):
        load_topic_set(project, cfg_for("topics/main.csv"), "main")


def test_unslugable_name_fails(project):
    write_csv(project, 'name,description\n"???","Only punctuation."\n')
    with pytest.raises(ToolkitError, match="invalid topic id"):
        load_topic_set(project, cfg_for("topics/main.csv"), "main")


def test_missing_column_fails(project):
    write_csv(project, 'name,text\nEducation,"Schooling."\n')
    with pytest.raises(ToolkitError, match="'description' column"):
        load_topic_set(project, cfg_for("topics/main.csv"), "main")


def test_missing_file_fails(project):
    with pytest.raises(ToolkitError, match="not found"):
        load_topic_set(project, cfg_for("topics/nope.csv"), "main")


def test_unknown_set_lists_configured_sets(project):
    write_csv(project, CSV)
    with pytest.raises(ToolkitError, match="Unknown topic set"):
        load_topic_set(project, cfg_for("topics/main.csv"), "other")


def test_explicit_set_resolution(project):
    write_csv(project, CSV)
    cfg = cfg_for("topics/main.csv")
    assert load_topic_set(project, cfg, "main").name == "main"


# --- set discovery: drop a spreadsheet in topics/, no config editing ------------------------------

import yaml

from transcript_toolkit.steps.topics.taxonomy import (available_sets, discover_topic_files,
                                                      register_topic_set, resolve_set)


def test_set_discovered_from_topics_folder_and_registered(project, capsys):
    """The whole point: drop collection.csv into topics/, name it with --set, nothing else."""
    write_csv(project, CSV, name="topics/collection.csv")
    cfg = yaml.safe_load(project.config_path.read_text())["topics"]
    assert not cfg.get("sets")                                   # nothing configured yet

    name, entry = resolve_set(project, cfg, "collection")
    assert name == "collection"
    assert entry["file"] == "topics/collection.csv"
    assert entry["rollup"] == {"scheme": "flat", "threshold_pct": 30}
    assert "Registered topic set 'collection'" in capsys.readouterr().out

    written = yaml.safe_load(project.config_path.read_text())["topics"]["sets"]["collection"]
    assert written == {"file": "topics/collection.csv",
                       "rollup": {"scheme": "flat", "threshold_pct": 30}}


def test_registration_preserves_comments(project):
    """config.yaml's comments ARE the user documentation — a yaml round-trip would delete them."""
    before = project.config_path.read_text()
    n_comments = sum(1 for ln in before.splitlines() if ln.strip().startswith("#"))
    write_csv(project, CSV, name="topics/collection.csv")
    assert register_topic_set(project, "collection", "topics/collection.csv")
    after = project.config_path.read_text()
    assert sum(1 for ln in after.splitlines() if ln.strip().startswith("#")) == n_comments
    assert "# --- locations:" in after and 'name: "My Oral History Project"' in after


def test_registration_is_idempotent_and_second_set_appends(project):
    write_csv(project, CSV, name="topics/collection.csv")
    write_csv(project, CSV, name="topics/filter.csv")
    assert register_topic_set(project, "collection", "topics/collection.csv")
    assert not register_topic_set(project, "collection", "topics/collection.csv")   # already there
    assert register_topic_set(project, "filter", "topics/filter.csv")
    sets = yaml.safe_load(project.config_path.read_text())["topics"]["sets"]
    assert sorted(sets) == ["collection", "filter"]


def test_xlsx_is_discovered_too(project):
    wb = Workbook()
    ws = wb.active
    ws.append(["name", "description"])
    ws.append(["Education", "Schooling."])
    wb.save(project.topics_dir / "collection.xlsx")
    assert discover_topic_files(project)["collection"].suffix == ".xlsx"
    name, entry = resolve_set(project, {"sets": {}}, "collection")
    assert entry["file"] == "topics/collection.xlsx"


def test_example_template_is_not_a_set(project):
    """example_topics.csv ships in every workspace; it's a template to fill in and rename."""
    assert (project.topics_dir / "example_topics.csv").exists()
    assert discover_topic_files(project) == {}
    assert available_sets(project, {"sets": {}}) == []
    with pytest.raises(ToolkitError, match="rename it to the set name"):
        resolve_set(project, {"sets": {}}, "anything")


def test_no_set_given_errors_and_lists_available(project):
    write_csv(project, CSV, name="topics/collection.csv")
    with pytest.raises(ToolkitError, match="No topic set given"):
        resolve_set(project, {"sets": {}}, None)
    with pytest.raises(ToolkitError, match="Available: collection"):
        resolve_set(project, {"sets": {}}, None)


def test_malformed_config_does_not_get_mangled(project):
    """If we can't safely edit the config we leave it untouched and the caller tells the user."""
    project.config_path.write_text("topics: [this, is, a, list]\n")
    assert not register_topic_set(project, "collection", "topics/collection.csv")
    assert project.config_path.read_text() == "topics: [this, is, a, list]\n"
