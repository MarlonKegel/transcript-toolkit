# locations

`toolkit locations` — tag each clip with the **countries and regions** it is substantively
about, map regions down to countries, and roll up to interview-level tags. Needs `clip`. Works
out of the box — a region vocabulary and a region→country mapping ship with the toolkit.

## Run it

```sh
toolkit locations tag --demo   # tag a sample of clips → review page opens in your browser
toolkit locations tag          # full corpus  (asks: run now, or 50%-off Batch API?)
toolkit locations map          # expand regions to countries, apply the label canon
toolkit locations thresholds   # compare how tags could be decided (writes a page)
toolkit locations rollup       # apply it: clip tags → interview tags
```

`toolkit locations preview --clip <id>` prints the request for one clip.

## The vocabulary is yours to edit

- `locations/regions.yaml` — the region names the model may use (a strict list; ships with a UN
  Geoscheme-based default plus common historical/political regions). Editing it changes both the
  prompt and the allowed outputs, so they never drift. **In the app**: *The regions the model may
  use*, on the Locations page — it also says which of them `region_to_country.csv` has no
  countries for, since `map` refuses a region it does not know.
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

## Rolling up: decide, then do

Same moves as [topics](topics.md#rolling-up-decide-then-do), and the same rule methods (see
[CONFIG.md](../CONFIG.md)); `locations.rollup` holds the choice, and the default is
`{ method: freq_width, bins: 5, range: [10, 30] }`. `toolkit locations thresholds` writes
`diags/locations/locations_thresholds.html`.

What is particular to places is the **hybrid rollover**, which the comparison works through so
its counts are the ones a rollup would really write. Two rollovers run per narrator under the
same rule:

1. **Direct places** — an interview is tagged a place when enough of its clips name that place
   with direct evidence.
2. **Regions** — an interview is tagged a region when enough of its clips are about that region;
   only then is the region expanded into its countries (`region_to_country.csv` + `relabel`).

The interview's places are the union of the two. So a country arrives through a region only when
the *region itself* is what the interview is about — not by accumulating scattered per-country
shares, which would quietly tag a lot of countries nobody talked about. The last panel of the
comparison page shows that choice against the two simpler alternatives. A place that only ever
comes up inside a region has no bar of its own; on the page it is drawn grey, with the bar of the
region that carried it in.

## Output

`outputs/locations/clip_locations*.parquet` (raw tags), `clip_countries*.parquet` (after
region→country mapping), `interview_locations_*.parquet` and `interview_regions_long.parquet`
(interview tags).
