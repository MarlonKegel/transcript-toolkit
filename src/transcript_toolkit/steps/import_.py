"""`toolkit import` — parse the workspace's .docx transcripts into data/paragraphs.parquet.

Validates loudly at the door (this is where naming/format mistakes must surface, not later):
- duplicate interview ids (two files collapsing to the same id) abort with both filenames;
- a file yielding zero paragraphs aborts with a pointer to the expected line format;
- the speaker-role table and the narrator-pooling table are printed for eyeballing.
Orphan paragraphs and stray mid-turn timestamps are logged to logs/import_warnings.log.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..core.config import load_step_config, require
from ..core.docx import parse_docx_paragraphs, paragraphs_to_records
from ..core.ids import interview_id_from_filename, narrator_key
from ..errors import ToolkitError
from ..project import Project

EXPECTED_FORMAT_HINT = (
    "every speaker turn must start with a paragraph like `[HH:MM:SS] SPEAKER: text` "
    "(SYNC'd transcript). See docs/steps/import.md for the expected format."
)


def find_docx_files(project: Project) -> list[Path]:
    files = sorted(p for p in project.data_dir.rglob("*.docx")
                   if not p.name.startswith("~$"))  # Word lock files
    if not files:
        raise ToolkitError(f"No .docx transcripts found under {project.data_dir}/")
    return files


def run_import(project: Project) -> pd.DataFrame:
    cfg = load_step_config(project, "import")
    require(cfg, ["interviewer_labels", "strip_suffixes", "session_regex"], "import")
    files = find_docx_files(project)

    # Derive ids first and refuse duplicates before parsing anything.
    ids: dict[str, Path] = {}
    for path in files:
        iid = interview_id_from_filename(path, cfg["strip_suffixes"])
        if iid in ids:
            raise ToolkitError(
                f"Two transcripts yield the same interview id {iid!r}:\n"
                f"  {ids[iid].name}\n  {path.name}\n"
                f"Rename one of them (ids come from filenames minus {cfg['strip_suffixes']}).")
        ids[iid] = path

    records: list[dict] = []
    warnings: list[str] = []
    empty: list[str] = []
    for iid, path in ids.items():
        paragraphs, orphans, mid_turn = parse_docx_paragraphs(
            path, iid, cfg["interviewer_labels"], cfg.get("other_labels") or [])
        if not paragraphs:
            empty.append(path.name)
            continue
        records += paragraphs_to_records(paragraphs)
        for o in orphans:
            warnings.append(f"{path.name}: paragraph before any turn header (skipped): {o[:120]}")
        for t in mid_turn:
            warnings.append(f"{path.name}: stray mid-turn timestamp folded into previous turn: {t[:120]}")
    if empty:
        raise ToolkitError(
            "No parsable paragraphs in: " + ", ".join(empty) + f"\nCheck the files — {EXPECTED_FORMAT_HINT}")

    df = pd.DataFrame(records)
    project.data_dir.mkdir(parents=True, exist_ok=True)
    df.to_parquet(project.paragraphs_path, index=False)
    if cfg.get("write_csv", True):
        df.to_csv(project.paragraphs_path.with_suffix(".csv"), index=False)

    warn_path = project.logs_dir / "import_warnings.log"
    warn_path.parent.mkdir(parents=True, exist_ok=True)
    warn_path.write_text("\n".join(warnings) + ("\n" if warnings else ""))

    _print_summary(df, ids, cfg["session_regex"], warn_path, n_warnings=len(warnings))
    return df


def _print_summary(df: pd.DataFrame, ids: dict[str, Path], session_regex: str,
                   warn_path: Path, n_warnings: int) -> None:
    narrators: dict[str, list[str]] = {}
    for iid in ids:
        narrators.setdefault(narrator_key(iid, session_regex), []).append(iid)

    print(f"Imported {len(ids)} transcripts -> {len(df):,} paragraphs, "
          f"{len(narrators)} narrators.")

    print("\nSpeaker roles (check that interviewer labels are configured right):")
    roles = (df.groupby(["speaker_role", "speaker_label"]).size()
               .reset_index(name="n").sort_values(["speaker_role", "n"], ascending=[True, False]))
    for r in roles.itertuples():
        print(f"  {r.speaker_role:<12} {r.speaker_label:<24} {r.n:>6} paragraphs")

    multi = {k: v for k, v in narrators.items() if len(v) > 1}
    if multi:
        print("\nMulti-session narrators (sessions pooled for summaries and interview tags):")
        for key, session_ids in sorted(multi.items()):
            print(f"  {key:<32} <- {', '.join(sorted(session_ids))}")
    if n_warnings:
        print(f"\n{n_warnings} parse warning(s) -> {warn_path}")
