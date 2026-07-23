"""`toolkit import` — parse the workspace's .docx transcripts into data/paragraphs.parquet.

Validates loudly at the door (this is where naming/format mistakes must surface, not later):
- duplicate interview ids (two files collapsing to the same id) abort with both filenames;
- a file yielding zero paragraphs aborts with a pointer to the expected line format;
- the speaker-role table and the narrator-pooling table are printed for eyeballing.

Timestamps: the toolkit EXPECTS a `[HH:MM:SS]` on every paragraph (per-paragraph timing). It
still works when only each speaker turn is timestamped and multi-paragraph turns continue
without one — but then a clip's start/end time falls back to the speaker-turn's timestamp, so
per-clip timing is coarser. Import measures this per transcript and warns when timestamps are
per-turn-only. Details (that fallback, plus paragraphs before the first speaker turn) go to
logs/import_warnings.log.
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
    orphan_lines: list[str] = []       # paragraphs before the first speaker turn (real warning)
    note_lines: list[str] = []         # benign: continuation had a colon after its own timestamp
    empty: list[str] = []
    for iid, path in ids.items():
        paragraphs, orphans, mid_turn = parse_docx_paragraphs(
            path, iid, cfg["interviewer_labels"], cfg.get("other_labels") or [])
        if not paragraphs:
            empty.append(path.name)
            continue
        records += paragraphs_to_records(paragraphs)
        for o in orphans:
            orphan_lines.append(f"{path.name}: paragraph before any turn header (skipped): {o[:120]}")
        for t in mid_turn:
            note_lines.append(f"{path.name}: continuation paragraph with its own timestamp and a "
                              f"colon; kept with the current speaker (normal): {t[:100]}")
    if empty:
        raise ToolkitError(
            "No parsable paragraphs in: " + ", ".join(empty) + f"\nCheck the files — {EXPECTED_FORMAT_HINT}")

    df = pd.DataFrame(records)
    project.data_dir.mkdir(parents=True, exist_ok=True)
    df.to_parquet(project.paragraphs_path, index=False)
    if cfg.get("write_csv", True):
        df.to_csv(project.paragraphs_path.with_suffix(".csv"), index=False)

    regimes = timestamp_regimes(df)
    flagged = [r for r in regimes if not r["ok"]]

    warn_path = project.logs_dir / "import_warnings.log"
    warn_path.parent.mkdir(parents=True, exist_ok=True)
    _write_log(warn_path, flagged, orphan_lines, note_lines)

    _print_summary(df, ids, cfg["session_regex"], regimes, orphan_lines, note_lines, warn_path)
    return df


def timestamp_regimes(df: pd.DataFrame) -> list[dict]:
    """Per-transcript timestamp coverage. For each interview, `coverage` = the fraction of
    continuation paragraphs (those after a turn's first line) that carry their OWN [HH:MM:SS]
    (`sub_time_start`). Turn-first paragraphs always have one, so they don't count here.

    coverage 1.0  -> every paragraph is timestamped (the expected per-paragraph regime);
    coverage 0.0  -> timestamps only on speaker turns (tolerated; clip times fall back to the
                     turn's timestamp for the untimed paragraphs);
    in between     -> mixed. `ok` is True only for the fully-per-paragraph case.
    """
    rows: list[dict] = []
    for iid, g in df.groupby("interview_id", sort=True):
        cont = g[g["paragraph_idx_in_turn"] > 0]
        n_cont = len(cont)
        n_ts = int((cont["sub_time_start"].astype(str).str.len() > 0).sum()) if n_cont else 0
        coverage = (n_ts / n_cont) if n_cont else 1.0
        rows.append({"interview_id": iid, "n_cont": n_cont, "n_timed": n_ts,
                     "coverage": coverage, "ok": coverage >= 1.0})
    return rows


def _regime_label(r: dict) -> str:
    if r["coverage"] <= 0.0:
        return f"timestamps on speaker turns only (0 of {r['n_cont']} continuation paragraphs timed)"
    return (f"mixed — {r['coverage']:.0%} of {r['n_cont']} continuation paragraphs carry their "
            f"own timestamp")


def _write_log(path: Path, flagged: list[dict], orphan_lines: list[str],
               note_lines: list[str]) -> None:
    sections: list[str] = []
    if flagged:
        sections.append("=== Timestamp coverage (per-turn-only or mixed transcripts) ===\n"
                        "For paragraphs without their own timestamp, a clip's start/end time falls "
                        "back to the speaker-turn's timestamp, so per-clip timing is coarser.\n"
                        + "\n".join(f"  {r['interview_id']}: {_regime_label(r)}" for r in flagged))
    if orphan_lines:
        sections.append("=== Paragraphs before the first speaker turn (skipped) ===\n"
                        + "\n".join(orphan_lines))
    if note_lines:
        sections.append("=== Continuation paragraphs with a colon after their timestamp "
                        "(kept with the current speaker; normal) ===\n" + "\n".join(note_lines))
    path.write_text("\n\n".join(sections) + ("\n" if sections else ""))


def _print_summary(df: pd.DataFrame, ids: dict[str, Path], session_regex: str,
                   regimes: list[dict], orphan_lines: list[str], note_lines: list[str],
                   warn_path: Path) -> None:
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

    # Timestamps: the toolkit expects one per paragraph; warn when a transcript is per-turn-only.
    flagged = [r for r in regimes if not r["ok"]]
    if not flagged:
        print("\nTimestamps: every paragraph carries its own [HH:MM:SS] (per-paragraph timing).")
    else:
        print(f"\n⚠ Timestamps: {len(flagged)} of {len(regimes)} transcripts have timestamps only "
              f"on speaker turns, not every paragraph.")
        print("  Clip start/end times fall back to the speaker-turn's timestamp for the untimed "
              "paragraphs, so per-clip timing is coarser (the pipeline still runs).")
        for r in flagged:
            print(f"    {r['interview_id']:<34} {_regime_label(r)}")

    multi = {k: v for k, v in narrators.items() if len(v) > 1}
    if multi:
        print("\nMulti-session narrators (sessions pooled for summaries and interview tags):")
        for key, session_ids in sorted(multi.items()):
            print(f"  {key:<32} <- {', '.join(sorted(session_ids))}")

    if orphan_lines:
        print(f"\n{len(orphan_lines)} paragraph(s) appeared before the first speaker turn and were "
              f"skipped -> {warn_path}")
    if note_lines:
        print(f"\n{len(note_lines)} continuation paragraph(s) had a colon right after their "
              f"timestamp; kept with the current speaker (normal, not a problem).")
