# import

`toolkit import` — parse the transcripts in `data/` into `data/paragraphs.parquet`, the dataset
every other step reads.

## Input: transcript files

Put one `.docx` per interview (or per session) into `data/`. Requirements:

- **Timestamps.** Ideally **every paragraph** begins with its own `[HH:MM:SS]` (a fully SYNC'd
  transcript) — this gives the most precise per-clip start/end times. Each speaker turn must at
  minimum begin with `[HH:MM:SS] SPEAKER: text`. If a turn spans several paragraphs and only the
  first is timestamped, the toolkit still runs, but a clip that starts or ends mid-turn inherits
  the *turn's* timestamp, so its timing is coarser — import prints a **⚠ Timestamps** warning
  naming those transcripts. A file with no timestamps at all is rejected loudly.
- **File names → interview id.** The id is the filename with the `strip_suffixes` removed and
  spaces/commas turned into underscores, lowercased. `Ramos_Ana_20240115_session1_SYNC.docx` →
  `ramos_ana_20240115_session1`; `Ramos, Ana_SYNC.docx` → `ramos_ana`.
- **Multi-session interviews.** Name them `{Name}_{YYYYMMDD}_session{N}` so the toolkit groups a
  narrator's sessions together for summaries and interview-level tags. Single-file interviews
  need no session token.

## What it does

Reads the printed output carefully:

- **Speaker roles table** — every distinct speaker label, classed as Interviewer / Other /
  Narrator. If your interviewer shows up as "Narrator", set `import.interviewer_labels` in
  `config.yaml` to your interviewer's label(s) and re-run.
- **Timestamps line** — confirms every paragraph is timestamped, or warns (⚠) that some
  transcripts are timestamped per speaker-turn only (see above).
- **Narrator-pooling table** — which session files were grouped into one narrator. If a
  grouping is wrong, the filenames don't follow the session convention.
- Details (per-turn-only transcripts, paragraphs before the first turn, and benign
  continuation-paragraph notes) go to `logs/import_warnings.log`.

## Settings

`config.yaml` → `import`: `interviewer_labels`, `other_labels`, `strip_suffixes`.
`advanced/import.yaml`: `session_regex` (the multi-session token pattern), `write_csv`.

## Output

`data/paragraphs.parquet` (+ `.csv`). Re-running is safe and cheap; do it whenever you add or
change transcripts.

## Re-importing a corrected transcript

A corrected transcript comes back under the filename it always had — drop it into `data/` (or
onto the app, which replaces the old file and says so) and run `toolkit import` again. Import
keeps a record of what each file looked like when it was read in, so it knows the difference
between the same file again and a changed one:

- **Unchanged files** keep their original imported-at timestamp — the record means "when this
  text came in", not "when import last ran".
- **A changed file** replaces its old rows AND takes its old results with it: the clips,
  labels, summaries and tags made from the superseded text are removed from `outputs/` (and
  any hand-edited labels for it), the steps show that there is work to do again, and import
  prints exactly what happened. Re-running the steps redoes only the changed interviews —
  everything else is already cached and comes back free.
- The **Interviews tab of the export** shows each transcript's imported-at date and time, so a
  spreadsheet can be checked against a correction: exported before the correction was imported
  means that row is out of date.

## Transcripts that were never SYNC'd

Sometimes a narrator revises a transcript so heavily that the recording no longer matches it,
and the edited text becomes the record. Those transcripts have no timestamps and never will.
Put them in `data/unsynced/`.

`toolkit import` reads that folder along with `data/`, into the same dataset — so these
interviews are clipped, labelled, summarized and tagged like every other one. A clip is a run of
paragraphs, and paragraph numbers are something every transcript has. **The one difference is
that their clips have no start and end time**, so those cells are empty in the spreadsheet and
the review pages show a paragraph range (`¶12–¶19`) where the others show a time.

- A turn starts at `SPEAKER: text`; every other paragraph continues the turn it is in. A label
  on every one of a speaker's paragraphs (`Hellam:` before each) is fine.
- Everything before the first speaker — the title page, the preface — is **left out** of the
  interview and written to `logs/import_warnings.log`, so you can check what was dropped.
- The same narrator must not be in both folders: sessions are pooled by name, so one person
  arriving from both would be two half-interviews claiming one row. Import refuses it and says
  which pair.
- `toolkit import --unsynced` still works and does exactly what `toolkit import` does.

**Why two folders, if it is all one collection?** Because a transcript with no timestamps in
`data/` is usually a mistake — a wrong file, a broken export — and import fails loudly on it
rather than quietly treating it as text-only. Moving it to `data/unsynced/` is how you say the
missing times are deliberate.

In the app this is on the Workspace page, folded under the transcript list.
