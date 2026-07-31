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

`--unsynced` is the one way into the toolkit for a transcript with no timestamps at all
(`run_import_unsynced`). It reads `data/unsynced/` into a table of its own, and only
`toolkit summarize --unsynced` ever looks at that table: a clip is a span between two times, so
without them there is nothing to clip, label or tag.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..core.config import load_step_config, require
from ..core.docx import parse_docx_paragraphs, parse_untimed_paragraphs, paragraphs_to_records
from ..core.ids import interview_id_from_filename, narrator_key
from ..errors import ToolkitError
from ..project import Project

EXPECTED_FORMAT_HINT = (
    "every speaker turn must start with a paragraph like `[HH:MM:SS] SPEAKER: text` "
    "(SYNC'd transcript). See docs/steps/import.md for the expected format."
)


def find_docx_files(project: Project) -> list[Path]:
    files = sorted(p for p in project.data_dir.rglob("*.docx")
                   if not p.name.startswith("~$")            # Word lock files
                   and project.unsynced_dir not in p.parents)   # summaries only; see below
    if not files:
        raise ToolkitError(f"No .docx transcripts found under {project.data_dir}/")
    return files


def find_unsynced_files(project: Project) -> list[Path]:
    files = sorted(p for p in project.unsynced_dir.rglob("*.docx")
                   if not p.name.startswith("~$"))
    if not files:
        raise ToolkitError(
            f"No .docx transcripts found under {project.unsynced_dir}/\n"
            f"That folder is for transcripts that were never SYNC'd — they can only be "
            f"summarized. SYNC'd transcripts belong in {project.data_dir}/ instead.")
    return files


def _ids_for(files: list[Path], strip_suffixes) -> dict[str, Path]:
    """{interview id: file}, refusing duplicates before anything is parsed."""
    ids: dict[str, Path] = {}
    for path in files:
        iid = interview_id_from_filename(path, strip_suffixes)
        if iid in ids:
            raise ToolkitError(
                f"Two transcripts yield the same interview id {iid!r}:\n"
                f"  {ids[iid].name}\n  {path.name}\n"
                f"Rename one of them (ids come from filenames minus {strip_suffixes}).")
        ids[iid] = path
    return ids


def run_import(project: Project) -> pd.DataFrame:
    cfg = load_step_config(project, "import")
    require(cfg, ["interviewer_labels", "strip_suffixes", "session_regex"], "import")
    files = find_docx_files(project)
    ids = _ids_for(files, cfg["strip_suffixes"])

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


def run_import_unsynced(project: Project) -> pd.DataFrame:
    """Read `data/unsynced/` — transcripts that were never SYNC'd — into their own table.

    They are kept apart from the corpus all the way through, because without timestamps there is
    no clipping and so no labels, topics or places: a summary is the only thing the toolkit can
    make from one. The summaries themselves do land in the same deliverable as the corpus's, so
    the one thing this refuses outright is a transcript belonging to somebody who is already in
    the corpus — two rows for one narrator would overwrite each other.
    """
    cfg = load_step_config(project, "import")
    require(cfg, ["interviewer_labels", "strip_suffixes", "session_regex"], "import")
    files = find_unsynced_files(project)
    ids = _ids_for(files, cfg["strip_suffixes"])
    _refuse_narrators_already_in_the_corpus(project, ids, cfg["session_regex"])

    records: list[dict] = []
    front_lines: list[str] = []
    empty: list[str] = []
    for iid, path in ids.items():
        paragraphs, front_matter = parse_untimed_paragraphs(
            path, iid, cfg["interviewer_labels"], cfg.get("other_labels") or [])
        if not paragraphs:
            empty.append(path.name)
            continue
        records += paragraphs_to_records(paragraphs)
        for line in front_matter:
            front_lines.append(f"{path.name}: {line[:160]}")
    if empty:
        raise ToolkitError(
            "No speaker turns found in: " + ", ".join(empty) + "\nEvery turn has to start with a "
            "paragraph like `SPEAKER: text`. See docs/steps/import.md.")

    df = pd.DataFrame(records)
    project.data_dir.mkdir(parents=True, exist_ok=True)
    df.to_parquet(project.unsynced_paragraphs_path, index=False)
    if cfg.get("write_csv", True):
        df.to_csv(project.unsynced_paragraphs_path.with_suffix(".csv"), index=False)

    warn_path = project.logs_dir / "import_unsynced.log"
    warn_path.parent.mkdir(parents=True, exist_ok=True)
    warn_path.write_text(
        "=== Front matter (everything before the first speaker; not summarized) ===\n"
        + "\n".join(front_lines) + "\n" if front_lines else "")

    narrators = narrator_groups(ids, cfg["session_regex"])
    print(f"Imported {len(ids)} transcript(s) that were never SYNC'd -> {len(df):,} paragraphs, "
          f"{len(narrators)} narrator(s).")
    print("\nSpeaker roles (check that interviewer labels are configured right):")
    for r in speaker_role_rows(df):
        print(f"  {r['speaker_role']:<12} {r['speaker_label']:<24} {r['n']:>6} paragraphs")
    multi = {k: v for k, v in narrators.items() if len(v) > 1}
    if multi:
        print("\nMulti-session narrators (sessions pooled into one summary):")
        for key, session_ids in sorted(multi.items()):
            print(f"  {key:<32} <- {', '.join(sorted(session_ids))}")
    if front_lines:
        print(f"\n{len(front_lines)} paragraph(s) before the first speaker — a title page or a "
              f"preface — were left out of the interview -> {warn_path}")
    print("\nThese can be summarized and nothing else: `toolkit summarize --unsynced --demo`.")
    return df


def _refuse_narrators_already_in_the_corpus(project: Project, ids: dict[str, Path],
                                            session_regex: str) -> None:
    if not project.paragraphs_path.exists():
        return
    corpus = pd.read_parquet(project.paragraphs_path, columns=["interview_id"])
    known = {narrator_key(i, session_regex): i for i in corpus["interview_id"].unique()}
    clash = [(path.name, known[narrator_key(iid, session_regex)])
             for iid, path in ids.items() if narrator_key(iid, session_regex) in known]
    if clash:
        listed = "\n".join(f"  {name}  is the same narrator as the imported {other}"
                           for name, other in clash)
        raise ToolkitError(
            f"These are already in the collection as SYNC'd transcripts:\n{listed}\n"
            f"Summaries are keyed by narrator, so one of the two would overwrite the other. "
            f"Remove them from {project.unsynced_dir}/, or take the SYNC'd ones out of the "
            f"collection and import again.")


def unsynced_interview_rows(project: Project) -> list[dict]:
    """One row per transcript that was never SYNC'd, for whoever arrives after the import."""
    if not project.unsynced_paragraphs_path.exists():
        return []
    cfg = load_step_config(project, "import")
    df = pd.read_parquet(project.unsynced_paragraphs_path)
    groups = narrator_groups(sorted(df["interview_id"].unique()), cfg["session_regex"])
    narrator_of = {iid: key for key, ids in groups.items() for iid in ids}
    return [{"interview_id": iid,
             "narrator": narrator_of[iid],
             "sessions": len(groups[narrator_of[iid]]),
             "paragraphs": int(len(g)),
             "words": int(g["word_count"].sum())}
            for iid, g in df.groupby("interview_id", sort=True)]


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


def speaker_role_rows(df: pd.DataFrame) -> list[dict]:
    """Paragraph counts per (role, speaker label) — the table that shows at a glance whether
    the interviewer labels in config.yaml matched what is actually in the transcripts."""
    roles = (df.groupby(["speaker_role", "speaker_label"]).size()
               .reset_index(name="n").sort_values(["speaker_role", "n"], ascending=[True, False]))
    return [{"speaker_role": r.speaker_role, "speaker_label": r.speaker_label, "n": int(r.n)}
            for r in roles.itertuples()]


def narrator_groups(interview_ids, session_regex: str) -> dict[str, list[str]]:
    """{narrator: [interview ids]} — which session files count as one person."""
    groups: dict[str, list[str]] = {}
    for iid in interview_ids:
        groups.setdefault(narrator_key(iid, session_regex), []).append(iid)
    return groups


def dataset_summary(project: Project) -> dict:
    """The same tables `toolkit import` prints, rebuilt from the saved dataset.

    For readers that arrive after the fact (the app's import page) rather than watching the
    run: everything here comes from data/paragraphs.parquet, so it stays true for as long as
    that file is the current one.
    """
    if not project.paragraphs_path.exists():
        raise ToolkitError("Nothing imported yet in this workspace.")
    cfg = load_step_config(project, "import")
    df = pd.read_parquet(project.paragraphs_path)
    ids = sorted(df["interview_id"].unique())
    groups = narrator_groups(ids, cfg["session_regex"])
    regimes = timestamp_regimes(df)
    return {
        "n_transcripts": len(ids),
        "n_paragraphs": int(len(df)),
        "n_narrators": len(groups),
        "roles": speaker_role_rows(df),
        "regimes": regimes,
        "flagged": [{"interview_id": r["interview_id"], "detail": _regime_label(r)}
                    for r in regimes if not r["ok"]],
        "multi_session": {k: sorted(v) for k, v in sorted(groups.items()) if len(v) > 1},
    }


def interview_rows(project: Project) -> list[dict]:
    """One row per interview in the dataset: how much of it there is, whose it is, and whether
    every paragraph carries its own timestamp.

    The per-interview view of the same facts `dataset_summary` aggregates. Nothing prints this;
    it is here rather than in the app because it is a question about the dataset.
    """
    if not project.paragraphs_path.exists():
        return []
    cfg = load_step_config(project, "import")
    df = pd.read_parquet(project.paragraphs_path)
    regimes = {r["interview_id"]: r for r in timestamp_regimes(df)}
    groups = narrator_groups(sorted(df["interview_id"].unique()), cfg["session_regex"])
    narrator_of = {iid: key for key, ids in groups.items() for iid in ids}
    rows = []
    for iid, g in df.groupby("interview_id", sort=True):
        regime = regimes[iid]
        narrator = narrator_of[iid]
        rows.append({
            "interview_id": iid,
            "narrator": narrator,
            "sessions": len(groups[narrator]),
            "paragraphs": int(len(g)),
            "words": int(g["word_count"].sum()),
            "timestamps": "every paragraph" if regime["ok"] else _regime_label(regime),
            "timestamps_ok": bool(regime["ok"]),
        })
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
    narrators = narrator_groups(ids, session_regex)

    print(f"Imported {len(ids)} transcripts -> {len(df):,} paragraphs, "
          f"{len(narrators)} narrators.")

    print("\nSpeaker roles (check that interviewer labels are configured right):")
    for r in speaker_role_rows(df):
        print(f"  {r['speaker_role']:<12} {r['speaker_label']:<24} {r['n']:>6} paragraphs")

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
