"""Interview ids and narrator keys.

The interview id is derived from the transcript FILENAME; the whole pipeline keys on it.
Expected naming convention (documented in docs/steps/import.md):

    {Name parts}[_{YYYYMMDD}_session{N}]{suffixes}.docx     e.g.
    Abramovay_Pedro_20250428_session1_SYNC.docx  -> abramovay_pedro_20250428_session1
    Acemoglu, Daron_SYNC.docx                    -> acemoglu_daron

- `strip_suffixes` (config.yaml, import section) are removed from the end of the stem,
  case-insensitively, repeatedly, in any order (default: _SYNC, _final).
- Separators (commas, spaces) normalize to underscores; the id is lowercase.
- A trailing `_{YYYYMMDD}_session{N}` token (advanced/import.yaml `session_regex`) marks one
  session of a multi-session interview; `narrator_key` strips it IF PRESENT (no-op-safe), so
  session files pool per narrator and single-file interviews pass through unchanged.

`toolkit import` prints the resulting id/narrator table so mis-parses surface immediately.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..errors import ToolkitError

DEFAULT_SESSION_REGEX = r"_(?P<date>\d{8})_session(?P<n>\d+)$"


def interview_id_from_filename(path: Path | str, strip_suffixes: list[str]) -> str:
    stem = Path(path).stem
    changed = True
    while changed:
        changed = False
        for suffix in strip_suffixes:
            if suffix and stem.lower().endswith(suffix.lower()):
                stem = stem[: -len(suffix)]
                changed = True
    stem = stem.replace(",", " ")
    stem = re.sub(r"\s+", "_", stem.strip())
    stem = re.sub(r"_+", "_", stem).strip("_").lower()
    if not stem:
        raise ToolkitError(f"Filename {Path(path).name!r} yields an empty interview id "
                           f"after stripping suffixes {strip_suffixes}")
    return stem


def compile_session_regex(pattern: str) -> re.Pattern:
    try:
        rx = re.compile(pattern)
    except re.error as e:
        raise ToolkitError(f"Invalid session_regex {pattern!r}: {e}") from e
    return rx


def session_token(interview_id: str, session_regex: str = DEFAULT_SESSION_REGEX) -> dict | None:
    """Parsed session token of an id, or None for session-less ids.
    Returns {"date": str|None, "n": int|None} from the regex's named groups (if defined)."""
    m = compile_session_regex(session_regex).search(interview_id)
    if not m:
        return None
    groups = m.groupdict()
    return {"date": groups.get("date"), "n": int(groups["n"]) if groups.get("n") else None}


def narrator_key(interview_id: str, session_regex: str = DEFAULT_SESSION_REGEX) -> str:
    """Pooling key: the id minus a trailing session token. No-op-safe — ids without the token
    (single-file interviews) are returned unchanged."""
    return compile_session_regex(session_regex).sub("", interview_id)
