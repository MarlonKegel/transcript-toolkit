# locations

`toolkit locations` — tag each clip with the **countries and regions** it is substantively
about, map regions down to countries, and roll up to interview-level tags. Needs `clip`. Works
out of the box — a region vocabulary and a region→country mapping ship with the toolkit.

## Run it

```sh
toolkit locations tag --demo   # tag a sample of clips → review page opens in your browser
toolkit locations tag          # full corpus  (add --batch for the 50%-off Batch API)
toolkit locations map          # expand regions to countries, apply the label canon
toolkit locations rollup       # clip tags → interview tags
```

`toolkit locations preview --clip <id>` prints the request for one clip.

## The vocabulary is yours to edit

- `locations/regions.yaml` — the region names the model may use (a strict list; ships with a UN
  Geoscheme-based default plus common historical/political regions). Editing it changes both the
  prompt and the allowed outputs, so they never drift.
- `locations/region_to_country.csv` — how each region expands to countries in the `map` step.
- `config.yaml` → `locations.relabel` — spelling/merge fixes applied to model output (e.g.
  `Czech Republic: Czechia`). `locations.place_tags` — subnational places to keep as their own
  tag (e.g. `Crimea`).

## Optional: survey your corpus first

If you want to build a custom region list, `toolkit locations survey` runs an offline
named-entity pass over your transcripts and reports the places mentioned. It needs the extra
dependencies (`pip install "transcript-toolkit[survey]"`, plus a spaCy model and a GeoNames dump
— the command tells you exactly what's missing).

## Reviewing

`diags/locations/demo.html` (opened for you after a demo) shows each clip with its country/region
tags (and justifications on demo runs); `toolkit locations annotate` writes the full-corpus
`locations.html`. Check that only substantive places are tagged, not passing mentions. The prompt
is `prompts/tag_locations.md`.

## Output

`outputs/locations/clip_locations*.parquet` (raw tags), `clip_countries*.parquet` (after
region→country mapping), `interview_locations_*.parquet` and `interview_regions_long.parquet`
(interview tags). `toolkit locations thresholds` is the rollup decision aid.
