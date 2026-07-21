import pytest
from openpyxl import Workbook

from transcript_toolkit.errors import ToolkitError
from transcript_toolkit.project import init_project
from transcript_toolkit.steps.topics.taxonomy import build_legend, load_topic_set


@pytest.fixture
def project(tmp_path):
    return init_project(str(tmp_path / "ws"))


def cfg_for(file, default_set="main"):
    return {"default_set": default_set, "sets": {"main": {"file": file}}}


def write_csv(project, text, name="topics/main.csv"):
    (project.root / name).write_text(text)


CSV = ('id,name,description\n'
       'education,Education,"Schooling of any kind."\n'
       ',Career and Work,"Jobs and workplaces."\n')

GOLDEN_TAXONOMY = ("## Education\n\nSchooling of any kind.\n\n"
                   "## Career and Work\n\nJobs and workplaces.")


def test_csv_happy_path(project):
    write_csv(project, CSV)
    tset = load_topic_set(project, cfg_for("topics/main.csv"))
    assert tset.name == "main"
    assert tset.ids == ["education", "career_and_work"]        # explicit id + slugged name
    assert tset.topics == [{"id": "education", "name": "Education"},
                           {"id": "career_and_work", "name": "Career and Work"}]
    assert tset.source == project.root / "topics" / "main.csv"


def test_taxonomy_text_byte_stable_golden(project):
    write_csv(project, CSV)
    tset = load_topic_set(project, cfg_for("topics/main.csv"))
    # BYTE-STABILITY GOLDEN: this text feeds cache keys and demo fingerprints — if this fails,
    # the generated format changed and every user's cache/demo would go stale.
    assert tset.taxonomy_text == GOLDEN_TAXONOMY


def test_legend_byte_stable_golden(project):
    write_csv(project, CSV)
    tset = load_topic_set(project, cfg_for("topics/main.csv"))
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
    tset = load_topic_set(project, cfg_for("topics/main.xlsx"))
    assert tset.ids == ["education", "career_and_work"]
    assert tset.taxonomy_text == GOLDEN_TAXONOMY               # identical across csv and xlsx


def test_slugging(project):
    write_csv(project, 'name,description\n"Community & Belonging! (2024)","Ties."\n')
    tset = load_topic_set(project, cfg_for("topics/main.csv"))
    assert tset.ids == ["community_belonging_2024"]


def test_duplicate_ids_fail_with_row_numbers(project):
    write_csv(project, 'name,description\n"Health, Care","A."\n"Health & Care","B."\n')
    with pytest.raises(ToolkitError, match=r"row 3.*duplicate topic id.*row 2"):
        load_topic_set(project, cfg_for("topics/main.csv"))


def test_missing_description_fails_with_row_number(project):
    write_csv(project, 'name,description\nEducation,"Fine."\nCareer,\n')
    with pytest.raises(ToolkitError, match=r"row 3.*empty description"):
        load_topic_set(project, cfg_for("topics/main.csv"))


def test_unslugable_name_fails(project):
    write_csv(project, 'name,description\n"???","Only punctuation."\n')
    with pytest.raises(ToolkitError, match="invalid topic id"):
        load_topic_set(project, cfg_for("topics/main.csv"))


def test_missing_column_fails(project):
    write_csv(project, 'name,text\nEducation,"Schooling."\n')
    with pytest.raises(ToolkitError, match="'description' column"):
        load_topic_set(project, cfg_for("topics/main.csv"))


def test_missing_file_fails(project):
    with pytest.raises(ToolkitError, match="not found"):
        load_topic_set(project, cfg_for("topics/nope.csv"))


def test_unknown_set_lists_configured_sets(project):
    write_csv(project, CSV)
    with pytest.raises(ToolkitError, match="Unknown topic set.*main"):
        load_topic_set(project, cfg_for("topics/main.csv"), "other")


def test_default_set_resolution(project):
    write_csv(project, CSV)
    cfg = cfg_for("topics/main.csv")
    assert load_topic_set(project, cfg).name == "main"         # default_set
    assert load_topic_set(project, cfg, "main").name == "main"  # explicit
