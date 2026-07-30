# Configuration reference

Two levels, both YAML, in the workspace:

- **`config.yaml`** — the settings you're expected to change. One section per step.
- **`advanced/<step>.yaml`** — everything else tunable, rarely needed.

For a given step the two are merged; a key set in `config.yaml` wins. **Changing any setting
that shapes an LLM call (model, reasoning, a prompt, a topic list) makes that step's previous
demo "stale"** — the next full run will ask you to demo and review again. That's intended.

**The comments in `config.yaml` are the documentation of each setting, and the app reads them.**
It shows the comment directly above a key (plus any comment on the key's own line) as that
setting's explanation, so rewording one here changes what the app says — there is one description
of a setting and this file is where it lives. Two conventions follow from that: keep a comment
directly above its key with no blank line between, and keep the two-space indentation, which is
what lets the app change one line and leave the rest of the file — comments included — exactly as
it was. A file that has been reindented by hand still works for every command; the app just
declines to write to it and tells you to make the change here yourself.

The app shows the settings in two places: those belonging to the whole project (its name) behind
the gear, and those belonging to one step on that step's own page. `advanced/` is not shown in
the app at all — those are files to edit.

## `config.yaml`

```yaml
project:
  name: "..."                     # shown in `toolkit status`, the app and the export.
                                  # Set by `toolkit init` from the folder name (or --name);
                                  # edit it here to rename the project without moving it.

import:
  interviewer_labels: [Q]         # speaker labels used by the interviewer
  other_labels: []                # other non-narrator voices (moderators, etc.)
  strip_suffixes: [_SYNC, _final] # filename endings removed to derive the interview id

clip:      { model: gpt-5.6-sol,      reasoning: medium }
label:     { model: gpt-5.6-terra,      reasoning: medium, addendum: null }
summarize: { model: gpt-5.6-sol,      reasoning: low,    pool_sessions: true }

topics:
  model: gpt-5.6-luna
  reasoning: medium
  sets:                           # written for you when a set is first used; no default set
    collection:
      file: topics/collection.xlsx  # your topic list (xlsx/csv: name, description, [id])
      rollup: { method: freq_width, bins: 5, range: [10, 30] }
      # or:  { method: equal_count, bins: 5, range: [10, 30] }
      # or:  { method: flat, threshold_pct: 30 }
      # prompt: tag_topics_strict.md   # this list's own rubric, a file in prompts/
      # model: gpt-5.6-sol             # and its own model / reasoning, overriding the two above
      # reasoning: high

locations:
  model: gpt-5.6-luna
  reasoning: medium
  rollup: { method: freq_width, bins: 5, range: [10, 30] }
  relabel: {}                     # output spelling/merge fixes, e.g. {Macedonia: North Macedonia}
  place_tags: []                  # subnational places kept as their own tag, e.g. [Crimea]
```

- **model / reasoning** — the OpenAI model and reasoning effort (`none|low|medium|high|xhigh`)
  for that step. Higher reasoning = better but pricier. Model ids the pricing table knows are in
  `defaults/pricing.yaml`.
- **label.addendum** — path (relative to the workspace) to project-specific labeling rules, or
  `null`.
- **summarize.pool_sessions** — pool a narrator's session files into one summary.
- **topics.sets** — one or more topic lists; each has a `file` and a `rollup` rule (below). A
  list may also carry its own `prompt`, `model` and `reasoning`, which override the `topics`
  section for that list alone — two lists are two pieces of work, with separate demos and
  separate caches.
- **rollup** (per topic list, and once for locations) — when a topic or place becomes one of an
  interview's tags. `method` is one of:
  - `freq_width` (the default) — the topics are split into `bins` bands by how often they come
    up across the collection, over `range: [lowest, highest]` percent of an interview's clips,
    and a rarer band clears a lower bar. Five bands over 10–30% are the bars 10, 15, 20, 25, 30.
    Two topics that come up equally often always get the same bar.
  - `equal_count` — the same, except each band holds the same number of topics. It spreads the
    bars evenly over your list, at the cost of splitting equally-frequent topics between bands.
  - `flat` — one `threshold_pct` bar for every topic.

  `toolkit topics thresholds --set <name>` and `toolkit locations thresholds` draw what each of
  these would tag before you choose. The older spelling (`scheme: flat|binned` with the bars
  written out as `thresholds: [...]`) is still read, and a hand-written bar list is still used
  exactly as written.
- **locations.relabel / place_tags** — see [steps/locations.md](steps/locations.md).
- **export.locations** — how location tags appear in the xlsx: `countries` (only those tagged
  directly), `countries_and_regions` (default; those countries plus a separate Regions column), or
  `countries_incl_regions` (one column, with regions mapped down into it). See
  [steps/export.md](steps/export.md).

## `advanced/<step>.yaml`

Per step: `prompt` (the file in `prompts/` used), `verbosity`, `max_workers`, poll settings, and
step-specific tunables — `clip`: `chunk_threshold_tokens`, `overlap_paragraphs`; `label`:
`batch_threshold_tokens` (how many clips share one request — nothing to do with the Batch API);
`topics`/`locations`: `demo_n_clips`, `demo_seed`, and for topics `score_values`,
`justify_min_score`; `import`: `session_regex`; `locations`: `regions_file`, `region_map_file`,
`survey.*`; `export`: `filename`, `tabs`.

The four steps that can use the Batch API (`label`, `summarize`, `topics`, `locations`) also take
`batch_poll_interval_s` and `batch_max_total_wait_s` — how often to check a submitted job, and
when to stop waiting (re-running the command resumes the same job).

## Prompts and vocabularies

Editable files, read live at run time (changing them re-stales the demo):

- `prompts/*.md` — one prompt per LLM step. Restore a pristine copy with
  `toolkit init --reset-prompt <name>`. `toolkit status` prints which file each step reads, and
  the app has the same file behind *The prompt for this step* on that step's page.
- `topics/*.csv|xlsx` — your topic lists.
- `locations/regions.yaml`, `locations/region_to_country.csv` — the location vocabulary and
  mapping.
