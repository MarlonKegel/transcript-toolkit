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
  column per topic set (the clip's tags), Locations (and Regions, depending on the mode below).
- **Interviews** — one row per narrator: Sessions, Summary, a column per topic set (interview
  tags), Locations (and Regions).
- **Categories** — the vocabularies (each topic set's names, the country and region lists) as
  reference columns. These follow the same mode, so you never see a reference value that appears
  in no row.

## How locations appear

The tagger records **countries** and **regions** separately, and `toolkit locations map` expands
each region into its countries. Pick which of those views the spreadsheet shows with
`config.yaml` → `export.locations` (or `--locations MODE` for a one-off):

| mode | Locations column | Regions column |
|---|---|---|
| `countries` | only countries tagged directly | — |
| `countries_and_regions` *(default)* | only countries tagged directly | the region tags |
| `countries_incl_regions` | direct countries **plus** the regions mapped down to countries | — |

For a clip tagged `Czechia` + the region `The Balkans` (which maps to Serbia, Croatia, …):

```
countries              Locations: Czechia
countries_and_regions  Locations: Czechia          Regions: The Balkans
countries_incl_regions Locations: Czechia, Serbia, Croatia, …
```

The first two never fold regions into the countries column, so each tag appears exactly once —
use `countries_incl_regions` when you want one country column that misses nothing. Subnational
**place tags** (`locations.place_tags`, e.g. Crimea) count as directly tagged in every mode; only
region *expansions* are what the modes add or withhold.

## A note on Google Sheets

This is a plain `.xlsx`. Excel has no "multiple selections per cell" validation, so the tag
columns are comma-separated text and the Categories tab is just a reference list. If you upload
the file to Google Sheets and want the tag columns to be multi-select dropdowns bound to the
Categories vocabulary, you add that validation in Sheets by hand — the toolkit can't set it in
an xlsx file.
