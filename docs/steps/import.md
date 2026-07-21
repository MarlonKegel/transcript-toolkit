# import

`toolkit import` — parse the transcripts in `data/` into `data/paragraphs.parquet`, the dataset
every other step reads.

## Input: transcript files

Put one `.docx` per interview (or per session) into `data/`. Requirements:

- **Timestamps.** Each speaker turn must begin with `[HH:MM:SS] SPEAKER: text` (a SYNC'd
  transcript). Paragraphs without that prefix are treated as continuations of the current turn.
  A file with no timestamps at all is rejected loudly.
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
- **Narrator-pooling table** — which session files were grouped into one narrator. If a
  grouping is wrong, the filenames don't follow the session convention.
- Parse oddities (paragraphs before the first turn, stray timestamps) go to
  `logs/import_warnings.log`.

## Settings

`config.yaml` → `import`: `interviewer_labels`, `other_labels`, `strip_suffixes`.
`advanced/import.yaml`: `session_regex` (the multi-session token pattern), `write_csv`.

## Output

`data/paragraphs.parquet` (+ `.csv`). Re-running is safe and cheap; do it whenever you add or
change transcripts.
