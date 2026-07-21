"""Parse oral history interview .docx transcripts into paragraph rows.

Ported from the working repo's shared/lib/docx_turns.py. Format expected: paragraphs of
`[HH:MM:SS] SPEAKER: text`. Paragraphs without that prefix are continuations of the previous
turn (a single turn often spans multiple paragraphs) and become their own rows.

Known transcript quirks handled here (do not "simplify" away):
- A line that matches the timestamp+colon shape but whose "label" is not name-shaped (e.g. a
  sentence ending in a colon) is a continuation with a stray fresh timestamp, not a new speaker
  (`is_plausible_label`).
- Continuation paragraphs may carry an embedded leading `[HH:MM:SS]`; it is stripped from the
  speech (kept in `sub_time_start`) so word counts stay accurate.
- Curly quotes and stray Unicode separators are normalized.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from docx import Document

LINE_RE = re.compile(r"^\[(\d{2}:\d{2}:\d{2})\]\s*([^:]+):\s*(.*)$")

# A real speaker label is short and looks like a name/code (Q, Goldston, Grudzinska-Gross, Q1, M1).
LABEL_RE = re.compile(r"^[A-Za-z][\w\-\.]*( [A-Za-z][\w\-\.]*)?$")

TIMESTAMP_PREFIX_RE = re.compile(r"^\[\d{2}:\d{2}:\d{2}\]\s*")

CURLY_QUOTES = {
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
}

# Stray Unicode separators/zero-width chars some .docx files embed mid-paragraph.
WEIRD_CHARS = {"\u2028": " ", "\u2029": " ", "\u200b": ""}


def is_plausible_label(label: str, max_len: int = 30) -> bool:
    return len(label) <= max_len and bool(LABEL_RE.match(label))


def normalize_text(s: str) -> str:
    for k, v in CURLY_QUOTES.items():
        s = s.replace(k, v)
    for k, v in WEIRD_CHARS.items():
        s = s.replace(k, v)
    return s


def infer_role(label: str, interviewer_labels: Iterable[str], other_labels: Iterable[str]) -> str:
    key = label.strip().casefold()
    if key in {x.casefold() for x in interviewer_labels}:
        return "Interviewer"
    if key in {x.casefold() for x in other_labels}:
        return "Other"
    return "Narrator"


@dataclass
class Paragraph:
    interview_id: str
    paragraph_idx: int            # 0-indexed within interview
    turn_idx: int                 # which speaker turn this paragraph belongs to
    paragraph_idx_in_turn: int    # 0 = the turn's timestamp+speaker line
    turn_time_start: str          # [HH:MM:SS] of the turn header
    sub_time_start: str           # embedded [HH:MM:SS] at start of a continuation, else ""
    speaker_label: str
    speaker_role: str
    speech: str
    word_count: int


def parse_docx_paragraphs(
    path: Path,
    interview_id: str,
    interviewer_labels: Iterable[str],
    other_labels: Iterable[str],
) -> tuple[list[Paragraph], list[str], list[str]]:
    """Parse one transcript. Returns (paragraphs, orphans, mid_turn_timestamps).

    `orphans` are non-empty paragraphs appearing before any turn header; `mid_turn_timestamps`
    are timestamp-shaped lines folded into the previous turn because their label was implausible.
    Both are reported by the import step, not silently dropped.
    """
    doc = Document(str(path))

    paragraphs: list[Paragraph] = []
    orphans: list[str] = []
    mid_turn: list[str] = []
    paragraph_idx = 0
    turn_idx = -1
    paragraph_idx_in_turn = 0
    turn_time_start = ""
    speaker_label = ""
    speaker_role = ""

    for p in doc.paragraphs:
        text = normalize_text(p.text).strip()
        if not text:
            continue
        m = LINE_RE.match(text)
        if m and is_plausible_label(m.group(2).strip()):
            # New turn header.
            turn_time_start = m.group(1)
            speaker_label = m.group(2).strip()
            speaker_role = infer_role(speaker_label, interviewer_labels, other_labels)
            speech = m.group(3).strip()
            turn_idx += 1
            paragraph_idx_in_turn = 0
        else:
            if turn_idx < 0:
                orphans.append(text)
                continue
            # Continuation paragraph. Strip any leading [HH:MM:SS] into sub_time_start.
            sub_time = ""
            if m:
                # Timestamp-shaped but implausible label: a stray fresh timestamp mid-turn.
                mid_turn.append(text)
                sub_time = m.group(1)
                speech = TIMESTAMP_PREFIX_RE.sub("", text).strip()
            else:
                ts_m = re.match(r"^\[(\d{2}:\d{2}:\d{2})\]\s*", text)
                if ts_m:
                    sub_time = ts_m.group(1)
                    speech = TIMESTAMP_PREFIX_RE.sub("", text).strip()
                else:
                    speech = text
            if not speech:
                continue
            paragraph_idx_in_turn += 1
            paragraphs.append(Paragraph(
                interview_id=interview_id,
                paragraph_idx=paragraph_idx,
                turn_idx=turn_idx,
                paragraph_idx_in_turn=paragraph_idx_in_turn,
                turn_time_start=turn_time_start,
                sub_time_start=sub_time,
                speaker_label=speaker_label,
                speaker_role=speaker_role,
                speech=speech,
                word_count=len(speech.split()),
            ))
            paragraph_idx += 1
            continue
        paragraphs.append(Paragraph(
            interview_id=interview_id,
            paragraph_idx=paragraph_idx,
            turn_idx=turn_idx,
            paragraph_idx_in_turn=paragraph_idx_in_turn,
            turn_time_start=turn_time_start,
            sub_time_start="",
            speaker_label=speaker_label,
            speaker_role=speaker_role,
            speech=speech,
            word_count=len(speech.split()),
        ))
        paragraph_idx += 1

    return paragraphs, orphans, mid_turn


def paragraphs_to_records(paragraphs: list[Paragraph]) -> list[dict]:
    return [asdict(p) for p in paragraphs]
