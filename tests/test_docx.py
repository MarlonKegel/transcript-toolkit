from pathlib import Path

from transcript_toolkit.core.docx import infer_role, is_plausible_label, parse_docx_paragraphs

FIXTURES = Path(__file__).parent / "fixtures"


def parse_alpha_s1():
    return parse_docx_paragraphs(
        FIXTURES / "Fake_Alpha_20240101_session1_SYNC.docx",
        "fake_alpha_20240101_session1",
        interviewer_labels=["Q"], other_labels=[],
    )


def test_structure_counts():
    paragraphs, orphans, mid_turn = parse_alpha_s1()
    assert len(paragraphs) == 12          # 13 docx paragraphs minus the orphan
    assert len(orphans) == 1
    assert orphans[0].startswith("Transcript of a fake interview")
    assert len(mid_turn) == 1
    assert max(p.turn_idx for p in paragraphs) == 7          # 8 speaker turns
    assert [p.paragraph_idx for p in paragraphs] == list(range(12))


def test_continuations_and_sub_timestamps():
    paragraphs, _, _ = parse_alpha_s1()
    # plain continuation: same turn, no timestamp
    plain = paragraphs[2]
    assert plain.paragraph_idx_in_turn == 1 and plain.turn_idx == 1
    assert plain.sub_time_start == "" and plain.speech.startswith("Looking back")
    # bare embedded timestamp: stripped into sub_time_start
    bare = paragraphs[3]
    assert bare.sub_time_start == "00:02:10"
    assert bare.speech.startswith("And then when I was fourteen")
    # stray mid-turn timestamp with sentence-shaped "label": folded into the Alpha turn
    stray = next(p for p in paragraphs if p.sub_time_start == "00:03:45")
    assert stray.speaker_label == "Alpha" and stray.paragraph_idx_in_turn == 1
    assert stray.speech.startswith("What she kept repeating was this:")


def test_roles_and_word_counts():
    paragraphs, _, _ = parse_alpha_s1()
    roles = {p.speaker_label: p.speaker_role for p in paragraphs}
    assert roles == {"Q": "Interviewer", "Alpha": "Narrator"}
    for p in paragraphs:
        assert p.word_count == len(p.speech.split())


def test_curly_quotes_normalized():
    paragraphs, _, _ = parse_alpha_s1()
    grants = next(p for p in paragraphs if "grants program" in p.speech)
    assert '"first grants program"' in grants.speech


def test_is_plausible_label():
    assert is_plausible_label("Q")
    assert is_plausible_label("Grudzinska-Gross")
    assert is_plausible_label("Q1") and is_plausible_label("M1")
    assert not is_plausible_label("What she kept repeating was this")
    assert not is_plausible_label("x" * 31)


def test_infer_role_other_labels():
    assert infer_role("M1", ["Q"], ["M1", "F1"]) == "Other"
    assert infer_role("q1", ["Q", "Q1"], []) == "Interviewer"   # case-insensitive
    assert infer_role("Goldston", ["Q"], []) == "Narrator"
