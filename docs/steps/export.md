# export

`toolkit export` — collect everything produced so far into one spreadsheet,
`outputs/export.xlsx`.

## Run it

```sh
toolkit export                 # -> outputs/export.xlsx
toolkit export --out final.xlsx
```

Incremental: it includes whatever steps have run. Clips only? You get a Clips tab with ids and
timings. Added labels, topics, locations, summaries? Each fills in its columns. Re-run any time;
it overwrites the file. `toolkit status` shows what the next export would include.

## What's in it

- **Clips** — one row per clip: Clip Id, Interview (narrator), Session, Start, End, Label, a
  column per topic set (the clip's tags), Locations, Regions.
- **Interviews** — one row per narrator: Sessions, Summary, a column per topic set (interview
  tags), Locations.
- **Categories** — the vocabularies (each topic set's names, the region and country lists) as
  reference columns.

## A note on Google Sheets

This is a plain `.xlsx`. Excel has no "multiple selections per cell" validation, so the tag
columns are comma-separated text and the Categories tab is just a reference list. If you upload
the file to Google Sheets and want the tag columns to be multi-select dropdowns bound to the
Categories vocabulary, you add that validation in Sheets by hand — the toolkit can't set it in
an xlsx file.
