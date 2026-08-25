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

Two folders, one dataset. `data/` holds SYNC'd transcripts; `data/unsynced/` holds transcripts
that were never SYNC'd, and one import reads both into `data/paragraphs.parquet`. They are
separate folders because they are read by different parsers and because a file with no times in
`data/` is a mistake worth failing on — not because what comes out of them is different. It is
not: a clip is a run of paragraphs, and paragraph numbers are something every transcript has, so
an untimed interview goes through the whole pipeline like any other. What it does not have is
times to show, and its clips say so by leaving them blank.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..core import manifest as manifest_mod
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
    """The SYNC'd pile: everything in data/ except the untimed folder inside it."""
    return sorted(p for p in project.data_dir.rglob("*.docx")
                  if not p.name.startswith("~$")             # Word lock files
                  and project.unsynced_dir not in p.parents)


def find_unsynced_files(project: Project) -> list[Path]:
    """The untimed pile. Empty is the normal case — most projects never have one."""
    if not project.unsynced_dir.is_dir():
        return []
    return sorted(p for p in project.unsynced_dir.rglob("*.docx")
                  if not p.name.startswith("~$"))


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
    """Read both folders into the one dataset every step works from."""
    cfg = load_step_config(project, "import")
    require(cfg, ["interviewer_labels", "strip_suffixes", "session_regex"], "import")
    timed = _ids_for(find_docx_files(project), cfg["strip_suffixes"])
    untimed = _ids_for(find_unsynced_files(project), cfg["strip_suffixes"])
    if not timed and not untimed:
        raise ToolkitError(f"No .docx transcripts found under {project.data_dir}/")
    _refuse_the_same_narrator_twice(timed, untimed, cfg["session_regex"])

    records: list[dict] = []
    orphan_lines: list[str] = []       # paragraphs before the first speaker turn (real warning)
    note_lines: list[str] = []         # benign: continuation had a colon after its own timestamp
    front_lines: list[str] = []        # an untimed transcript's title page and preface
    unreadable: list[str] = []

    for iid, path in timed.items():
        paragraphs, orphans, mid_turn = parse_docx_paragraphs(
            path, iid, cfg["interviewer_labels"], cfg.get("other_labels") or [])
        if not paragraphs:
            unreadable.append(path.name)
            continue
        records += paragraphs_to_records(paragraphs)
        for o in orphans:
            orphan_lines.append(f"{path.name}: paragraph before any turn header (skipped): {o[:120]}")
        for t in mid_turn:
            note_lines.append(f"{path.name}: continuation paragraph with its own timestamp and a "
                              f"colon; kept with the current speaker (normal): {t[:100]}")
    if unreadable:
        raise ToolkitError(
            "No parsable paragraphs in: " + ", ".join(unreadable)
            + f"\nCheck the files — {EXPECTED_FORMAT_HINT}\n"
            + f"If a transcript has no timestamps at all and never will, it belongs in "
              f"{project.unsynced_dir.name}/ inside the data folder.")

    for iid, path in untimed.items():
        paragraphs, front_matter = parse_untimed_paragraphs(
            path, iid, cfg["interviewer_labels"], cfg.get("other_labels") or [])
        if not paragraphs:
            unreadable.append(path.name)
            continue
        records += paragraphs_to_records(paragraphs)
        front_lines += [f"{path.name}: {line[:160]}" for line in front_matter]
    if unreadable:
        raise ToolkitError(
            "No speaker turns found in: " + ", ".join(unreadable) + "\nEvery turn has to start "
            "with a paragraph like `SPEAKER: text`. See docs/steps/import.md.")

    # The manifest knows what each file looked like when it was last imported. A changed or
    # vanished transcript takes its old results with it — the purge runs BEFORE the manifest is
    # saved, so a crash in between leaves the old hashes in place and the next import redoes
    # the purge instead of skipping it. Both piles are planned against the one manifest, so
    # neither plan discards the other's.
    updated = manifest_mod.load_manifest(project)
    updated, timed_diff = manifest_mod.plan_update(project, manifest_mod.SYNCED, timed, updated)
    updated, untimed_diff = manifest_mod.plan_update(project, manifest_mod.UNSYNCED, untimed,
                                                     updated)
    diff = {kind: timed_diff[kind] + untimed_diff[kind] for kind in ("new", "changed", "gone")}
    outdated = diff["changed"] + diff["gone"]
    purged = _purge_results(project, outdated, cfg["session_regex"]) if outdated else []

    df = pd.DataFrame(records)
    project.data_dir.mkdir(parents=True, exist_ok=True)
    df.to_parquet(project.paragraphs_path, index=False)
    if cfg.get("write_csv", True):
        df.to_csv(project.paragraphs_path.with_suffix(".csv"), index=False)
    manifest_mod.save_manifest(project, updated)
    _put_away_the_old_untimed_table(project)

    regimes = timestamp_regimes(df)
    flagged = [r for r in regimes if not r["ok"]]

    warn_path = project.logs_dir / "import_warnings.log"
    warn_path.parent.mkdir(parents=True, exist_ok=True)
    _write_log(warn_path, flagged, orphan_lines, note_lines, front_lines)

    _print_summary(df, {**timed, **untimed}, cfg["session_regex"], regimes,
                   orphan_lines, note_lines, front_lines, warn_path)
    _print_changes(diff, purged)
    return df


def run_import_unsynced(project: Project) -> pd.DataFrame:
    """`toolkit import --unsynced`, kept as it was typed before both folders were read together.

    There is one import now, so this is that import. Saying so matters more than saving the
    words: somebody following an older note would otherwise think the untimed folder had been
    skipped this time.
    """
    print(f"Every import reads {project.unsynced_dir.name}/ as well now — importing both.\n")
    return run_import(project)


def _put_away_the_old_untimed_table(project: Project) -> None:
    """Clear away the separate table untimed transcripts used to live in.

    They are in `paragraphs.parquet` with everything else now. The docx files and the manifest
    are what a project is made of, so nothing is lost by dropping the old table — but leaving
    it on disk would leave two answers to "what is in this project?".
    """
    from ..state import load_state, save_state

    gone = []
    for path in (project.unsynced_paragraphs_path,
                 project.unsynced_paragraphs_path.with_suffix(".csv")):
        if path.exists():
            path.unlink()
            gone.append(path.name)

    state = load_state(project)
    # Its summaries were recorded under a step of their own. One pile means one record; the
    # count is recovered by the next `toolkit summarize`, which finds more to do and says so.
    if state.get("steps", {}).pop("summarize:unsynced", None) is not None:
        save_state(project, state)
        gone.append("their separate record of what had been summarized")
    if gone:
        print(f"\nTranscripts that were never SYNC'd are part of the collection now, so "
              f"{' and '.join(gone)} {'have' if len(gone) > 1 else 'has'} been cleared away. "
              f"They can be clipped, labelled and tagged like the rest; run the steps again to "
              f"include them (what is already done stays done).\n")


def _purge_results(project: Project, ids: list[str], session_regex: str) -> list[Path]:
    """Remove every processing result made from these interviews' old text.

    A corrected transcript replaces the old one, results included: rows for the changed ids
    (and their narrators) are dropped from every table under outputs/ and the demo tables.
    Caches are untouched — they key on the text itself — so re-running a step redoes only the
    changed interviews and the rest comes back free."""
    wanted = set(ids)
    narrators = {narrator_key(i, session_regex) for i in ids}
    touched: list[Path] = []
    for folder in (project.outputs_dir, project.demo_dir):
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*.parquet")):
            table = pd.read_parquet(path)
            for column, gone in (("interview_id", wanted), ("interview_key", narrators)):
                if column not in table.columns:
                    continue
                keep = ~table[column].isin(gone)
                if not keep.all():
                    kept = table[keep]
                    kept.to_parquet(path, index=False)
                    csv = path.with_suffix(".csv")
                    if csv.exists():
                        kept.to_csv(csv, index=False)
                    touched.append(path)
                break
    from ..core import overrides as overrides_mod
    if overrides_mod.purge_interviews(project, ids):
        touched.append(project.label_overrides_path)
    if touched:
        _lower_unit_counts(project)
    return touched


def _lower_unit_counts(project: Project) -> None:
    """Full-run records say how many units they covered; purged rows shrink that coverage.

    Recounted from the deliverables themselves, so `freshness` (and the app's greyed-out
    buttons) report the purged interviews as work remaining rather than done."""
    from ..state import load_state, save_state

    state = load_state(project)
    lowered = False
    for key, record in state.get("steps", {}).items():
        full = record.get("full")
        if not full:
            continue
        covered = _covered(project, key)
        if covered is not None and covered < int(full.get("n_units") or 0):
            full["n_units"] = covered
            lowered = True
    if lowered:
        save_state(project, state)


def _covered(project: Project, step_key: str) -> int | None:
    """What the deliverable on disk still covers, counted the way the step counts its units:
    interviews for clip and label, narrators for summarize, clips for topics and locations."""
    out = project.outputs_dir

    def distinct(path: Path, column: str) -> int | None:
        if not path.exists():
            return None
        return int(pd.read_parquet(path, columns=[column])[column].nunique())

    if step_key == "clip":
        return distinct(out / "clips" / "clips.parquet", "interview_id")
    if step_key == "label":
        return distinct(out / "labels" / "labels.parquet", "interview_id")
    if step_key == "summarize":
        return distinct(out / "summaries" / "summaries.parquet", "interview_key")
    if step_key.startswith("topics:"):
        set_name = step_key.split(":", 1)[1]
        path = out / "topics" / f"{set_name}_clip_topics_wide.parquet"
        return None if not path.exists() else int(len(pd.read_parquet(path)))
    if step_key == "locations":
        path = out / "locations" / "clip_locations.parquet"
        return None if not path.exists() else int(len(pd.read_parquet(path)))
    return None


def _print_changes(diff: dict, purged: list[Path]) -> None:
    """What this import replaced, said out loud — silence here would leave results made from
    superseded text sitting in outputs/ looking finished."""
    if diff["changed"]:
        print(f"\n{len(diff['changed'])} transcript(s) changed since they were last imported: "
              + ", ".join(sorted(diff["changed"])))
    if diff["gone"]:
        print(f"\n{len(diff['gone'])} previously imported transcript(s) are no longer in the "
              f"folder: " + ", ".join(sorted(diff["gone"])))
    if purged:
        print("  Results made from the old text were removed — run the steps again to redo "
              "just these; everything unchanged stays done, and its calls stay cached.")


def _refuse_the_same_narrator_twice(timed: dict[str, Path], untimed: dict[str, Path],
                                    session_regex: str) -> None:
    """One narrator, one place in the collection.

    Both folders read into one dataset, and a narrator's sessions are pooled by name — so the
    same person arriving from both piles would be two half-interviews claiming one row.
    """
    known = {narrator_key(iid, session_regex): path.name for iid, path in timed.items()}
    clash = [(path.name, known[narrator_key(iid, session_regex)])
             for iid, path in untimed.items() if narrator_key(iid, session_regex) in known]
    if clash:
        listed = "\n".join(f"  {name}  is the same narrator as {other}"
                           for name, other in clash)
        raise ToolkitError(
            f"These transcripts are in both transcript folders:\n{listed}\n"
            f"Keep one of each pair: the SYNC'd version if there is one, since it can be "
            f"clipped and tagged as well as summarized.")


def timestamp_regimes(df: pd.DataFrame) -> list[dict]:
    """Per-transcript timestamp coverage. For each interview, `coverage` = the fraction of
    continuation paragraphs (those after a turn's first line) that carry their OWN [HH:MM:SS]
    (`sub_time_start`). Turn-first paragraphs always have one, so they don't count here.

    coverage 1.0  -> every paragraph is timestamped (the expected per-paragraph regime);
    coverage 0.0  -> timestamps only on speaker turns (tolerated; clip times fall back to the
                     turn's timestamp for the untimed paragraphs);
    in between     -> mixed. `ok` is True only for the fully-per-paragraph case.

    Transcripts that were never SYNC'd are left out. They have no timestamps by definition, and
    counting them here would report the thing that is true of them as a fault in them.
    """
    from ..core.tables import untimed_ids

    never_synced = untimed_ids(df)
    rows: list[dict] = []
    for iid, g in df.groupby("interview_id", sort=True):
        if iid in never_synced:
            continue
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
               note_lines: list[str], front_lines: list[str] = ()) -> None:
    sections: list[str] = []
    if front_lines:
        sections.append("=== Front matter of transcripts that were never SYNC'd ===\n"
                        "Everything before the first speaker — a title page, a preface — is "
                        "about the interview rather than part of it, so it is left out.\n"
                        + "\n".join(front_lines))
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
                   front_lines: list[str], warn_path: Path) -> None:
    from ..core.tables import untimed_ids

    narrators = narrator_groups(ids, session_regex)
    never_synced = untimed_ids(df)

    print(f"Imported {len(ids)} transcripts -> {len(df):,} paragraphs, "
          f"{len(narrators)} narrators.")
    if never_synced:
        print(f"  {len(never_synced)} of them were never SYNC'd, so they carry no times: "
              + ", ".join(sorted(never_synced)))
        print("  They go through every step like the rest; what their clips cannot show is a "
              "start and end time.")

    print("\nSpeaker roles (check that interviewer labels are configured right):")
    for r in speaker_role_rows(df):
        print(f"  {r['speaker_role']:<12} {r['speaker_label']:<24} {r['n']:>6} paragraphs")

    # Timestamps: the toolkit expects one per paragraph; warn when a transcript is per-turn-only.
    flagged = [r for r in regimes if not r["ok"]]
    if not regimes:
        pass                    # nothing SYNC'd in this project; there is no regime to report
    elif not flagged:
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

    if front_lines:
        print(f"\n{len(front_lines)} paragraph(s) before the first speaker — a title page or a "
              f"preface — were left out of the interview -> {warn_path}")
    if orphan_lines:
        print(f"\n{len(orphan_lines)} paragraph(s) appeared before the first speaker turn and were "
              f"skipped -> {warn_path}")
    if note_lines:
        print(f"\n{len(note_lines)} continuation paragraph(s) had a colon right after their "
              f"timestamp; kept with the current speaker (normal, not a problem).")
