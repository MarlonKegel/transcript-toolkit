# topics

`toolkit topics` — score every clip against a **topic list** you provide, then roll the clip
tags up to interview-level tags. Needs `clip` to have run.

## Provide a topic list

**Put a spreadsheet in `topics/`. The filename is the name of the set — that's the whole setup.**

`topics/collection.xlsx` → the set is called `collection`. Then:

```sh
toolkit topics tag --set collection --demo
```

The first time you use a set, the toolkit adds it to `config.yaml` for you, so its rollup
settings are there to adjust later. You never have to edit config to get started.

Every workspace ships with `topics/example_topics.csv` — **fill it in with your topics and
rename it** to whatever you want the set called. Or bring your own file; `.csv` and `.xlsx`
both work. The columns:

| column | required | notes |
|---|---|---|
| `name` | yes | the topic's display name (also the tag shown in the export) |
| `description` | yes | what belongs under it — the model reads *only* this to decide. Be specific: say what counts **and what doesn't**. |
| `id` | no | a short code; auto-derived from the name if omitted |

Several topic lists? Drop in several files. `topics/collection.xlsx` and `topics/filter.csv`
give you `--set collection` and `--set filter`, tagged independently, each with its own outputs.

**In the app** this is the Topics page: write the list in the table there, or upload a
spreadsheet. The table edits the same `topics/*.csv` file — it is checked against the rules
above as you save it, and the first save is where you name the set. Until you name it, what you
type is kept in `topics/example_topics.csv`, which no run will ever tag against.

There is **no default set** — every `toolkit topics` command needs `--set`. Tagging a whole
corpus against the wrong taxonomy is expensive, so the set is always named explicitly. Forget it
and the error lists the sets you have.

## Run it

```sh
toolkit topics tag --set collection --demo   # sample of clips → review page opens in your browser
toolkit topics tag --set collection          # full corpus
toolkit topics thresholds --set collection   # decision aid for the rollup bar(s)
toolkit topics rollup --set collection       # clip tags → interview tags
```

`toolkit topics preview --set collection --clip <id>` prints the exact request for one clip.
Demos include a per-topic justification by default (off for full runs) — useful for judging
borderline calls. A full run asks whether to run now or on the 50%-off
[Batch API](../WORKFLOW.md#run-now-or-run-cheap-the-batch-api) — worth considering here, since you
pay for a full pass per taxonomy.

## Reviewing and tuning

The demo opens `diags/topics/<set>_demo.html`; `toolkit topics annotate --set <name>` writes a
per-interview page for every tagged clip (linked from `<set>_index.html`). Each clip is scored
0/1/2 per topic (0 = no, 1 = maybe, 2 = yes); a clip is "tagged" with a topic at score 2. If
topics are over- or under-applied, sharpen the `description` in your spreadsheet and re-demo —
that text, not the code, is where the tagging rules live.

The **rollup** decides when an interview gets a topic: either a flat share-of-clips bar
(`rollup: {scheme: flat, threshold_pct: 30}`) or rarity-binned bars that ask more of common
topics than rare ones (`scheme: binned`). `toolkit topics thresholds --set <name>` shows the
trade-offs.

## Settings

`config.yaml` → `topics`: `model`, `reasoning`, `sets.<set>.{file, rollup, prompt}` (written for
you when a set is first used). `advanced/topics.yaml`: `score_values`, `justify_min_score`,
`demo_n_clips`, `max_workers`, `prompt`.

## Output

`outputs/topics/<set>_clip_topics_{wide,long}.parquet` (clip scores) and
`<set>_interview_topics_{wide,long}.parquet` (interview tags).
