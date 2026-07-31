"""The review pages, as somebody actually reads them.

They open in a browser tab of their own — from the app and from a double-click in Finder alike —
so getting from one interview back to the list of them has to be on the page. The browser's own
Back button works too, but it should not be the only way.
"""
import pandas as pd
import pytest

from transcript_toolkit.core.reviewdoc import BACK_LABEL, document, write_index


def test_a_page_with_a_way_back_says_where_it_goes():
    page = document("fake_beta", "<p>x</p>", back=("index.html", BACK_LABEL))
    assert '<a href="index.html">' in page
    assert BACK_LABEL in page
    assert page.index("index.html") < page.index("<h1>")       # above the title, not buried


def test_a_page_that_is_the_only_one_has_no_way_back():
    assert "class=\"back\"" not in document("Summaries", "<p>x</p>")


@pytest.fixture
def clipped(tmp_path):
    """One interview's paragraphs and clips, enough to render a review page from."""
    paragraphs = pd.DataFrame([
        {"interview_id": "fake_beta", "paragraph_idx": i, "clip_id": "fake_beta_01",
         "speaker_role": "Narrator", "speech": f"line {i}", "word_count": 2,
         "sub_time_start": "", "turn_time_start": "00:00:0%d" % i,
         "paragraph_idx_in_turn": 0, "speaker_label": "Beta"}
        for i in range(3)])
    clips = pd.DataFrame([{"clip_id": "fake_beta_01", "interview_id": "fake_beta",
                           "start_paragraph_idx": 0, "end_paragraph_idx": 2,
                           "n_paragraphs": 3, "total_words": 6, "duration_seconds": 60.0}])
    return paragraphs, clips


def test_the_clip_review_page_links_back_to_the_list(tmp_path, clipped):
    from transcript_toolkit.project import init_project
    from transcript_toolkit.steps.clip.annotate import write_annotated

    project = init_project(str(tmp_path / "ws"))
    paragraphs, clips = clipped
    diag_dir = write_annotated(project, ["fake_beta"], paragraphs, clips)

    page = (diag_dir / "fake_beta.html").read_text()
    assert f'href="index.html">&larr; {BACK_LABEL}' in page
    assert (diag_dir / "index.html").exists()


def test_the_topics_review_page_links_back_to_its_own_topic_lists_index():
    """Topics writes one index per topic list, so the way back has to name the set — otherwise
    every set's pages point at whichever index happens to be called index.html."""
    from transcript_toolkit.steps.topics.annotate import _render_interview

    page = _render_interview("fake_beta",
                             pd.DataFrame(columns=["paragraph_idx"]),
                             pd.DataFrame(columns=["clip_id", "start_paragraph_idx"]),
                             {}, "collection")
    assert 'href="collection_index.html"' in page


def test_the_index_page_needs_no_way_back(tmp_path):
    path = write_index(tmp_path / "index.html", "Clips — review",
                       [("fake_beta.html", "fake_beta", "3 clips")])
    assert 'class="back"' not in path.read_text()


def test_the_review_pages_are_drawn_in_the_toolkits_own_colours():
    """The same navy and cream as the app and the icon, so a review page does not look like it
    came from somewhere else."""
    page = document("x", "<p>y</p>")
    assert "#2a3e55" in page.lower()          # navy
    assert "#e7dfcc" in page.lower()          # cream, for the dark side
