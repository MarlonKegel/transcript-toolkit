import pytest

from transcript_toolkit.core.ids import (
    DEFAULT_SESSION_REGEX,
    interview_id_from_filename,
    narrator_key,
    session_token,
)
from transcript_toolkit.errors import ToolkitError

STRIP = ["_SYNC", "_final"]


def test_osf_style_filename():
    iid = interview_id_from_filename("Abramovay_Pedro_20250428_session1_SYNC.docx", STRIP)
    assert iid == "abramovay_pedro_20250428_session1"


def test_comma_style_filename():
    iid = interview_id_from_filename("Acemoglu, Daron_final_SYNC.docx", STRIP)
    assert iid == "acemoglu_daron"


def test_suffixes_strip_in_any_order_case_insensitive():
    assert interview_id_from_filename("X_sync_FINAL.docx", STRIP) == "x"
    assert interview_id_from_filename("X_final_SYNC.docx", STRIP) == "x"


def test_spaces_and_repeats_normalize():
    assert interview_id_from_filename("De La  Cruz,  Maria_SYNC.docx", STRIP) == "de_la_cruz_maria"


def test_empty_id_fails_loud():
    with pytest.raises(ToolkitError):
        interview_id_from_filename("_SYNC.docx", STRIP)


def test_narrator_key_strips_session_token():
    assert narrator_key("abramovay_pedro_20250428_session1") == "abramovay_pedro"


def test_narrator_key_noop_without_token():
    assert narrator_key("acemoglu_daron") == "acemoglu_daron"


def test_session_token_parses():
    tok = session_token("x_y_20250428_session2")
    assert tok == {"date": "20250428", "n": 2}
    assert session_token("x_y") is None


def test_bad_session_regex_fails_loud():
    with pytest.raises(ToolkitError):
        narrator_key("abc", session_regex="(unclosed")


def test_default_regex_anchored_at_end():
    # a session token mid-id must NOT be stripped
    assert narrator_key("a_20250428_session1_extra", DEFAULT_SESSION_REGEX) == "a_20250428_session1_extra"
