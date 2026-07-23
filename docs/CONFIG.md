# Configuration reference

Two levels, both YAML, in the workspace:

- **`config.yaml`** — the settings you're expected to change. One section per step.
- **`advanced/<step>.yaml`** — everything else tunable, rarely needed.

For a given step the two are merged; a key set in `config.yaml` wins. **Changing any setting
that shapes an LLM call (model, reasoning, a prompt, a topic list) makes that step's previous
demo "stale"** — the next full run will ask you to demo and review again. That's intended.

## `config.yaml`

```yaml
project:
  name: "..."                     # shown in `toolkit status` and the export

import:
  interviewer_labels: [Q]         # speaker labels used by the interviewer
  other_labels: []                # other non-narrator voices (moderators, etc.)
  strip_suffixes: [_SYNC, _final] # filename endings removed to derive the interview id

clip:      { model: gpt-5.5,      reasoning: medium }
label:     { model: gpt-5.4,      reasoning: medium, addendum: null }
summarize: { model: gpt-5.5,      reasoning: low,    pool_sessions: true }

topics:
  model: gpt-5.4-mini
  reasoning: medium
  default_set: main
  sets:
    main:
      file: topics/main.csv       # your topic list (xlsx/csv: name, description, [id])
      rollup: { scheme: flat, threshold_pct: 30 }
      # or:  { scheme: binned, thresholds: [10, 12.5, ..., 30] }

locations:
  model: gpt-5.4-mini
  reasoning: medium
  rollup: { thresholds: [10, 12.5, ..., 30] }
  relabel: {}                     # output spelling/merge fixes, e.g. {Macedonia: North Macedonia}
  place_tags: []                  # subnational places kept as their own tag, e.g. [Crimea]
```

- **model / reasoning** — the OpenAI model and reasoning effort (`none|low|medium|high|xhigh`)
  for that step. Higher reasoning = better but pricier. Model ids the pricing table knows are in
  `defaults/pricing.yaml`.
- **label.addendum** — path (relative to the workspace) to project-specific labeling rules, or
  `null`.
- **summarize.pool_sessions** — pool a narrator's session files into one summary.
- **topics.sets** — one or more topic lists; each has a `file` and a `rollup` scheme (`flat`
  with `threshold_pct`, or `binned` with a `thresholds` bar list, rarest band first).
- **locations.rollup.thresholds / relabel / place_tags** — see [steps/locations.md](steps/locations.md).

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
  `toolkit init --reset-prompt <name>`.
- `topics/*.csv|xlsx` — your topic lists.
- `locations/regions.yaml`, `locations/region_to_country.csv` — the location vocabulary and
  mapping.
