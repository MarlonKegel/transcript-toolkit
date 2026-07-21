# topics

`toolkit topics` — score every clip against a **topic list** you provide, then roll the clip
tags up to interview-level tags. Needs `clip` to have run.

## Provide a topic list

Put a spreadsheet at the path in `config.yaml` → `topics.sets.<set>.file` (default
`topics/main.csv`). Columns:

| column | required | notes |
|---|---|---|
| `name` | yes | the topic's display name (also the tag shown in the export) |
| `description` | yes | what belongs under it — the model reads this to decide. Be specific. |
| `id` | no | a short code; auto-derived from the name if omitted |

xlsx or csv both work. You can define several sets (e.g. a broad `collection` and a fine
`filter`) under `topics.sets` and pick one per command with `--set`.

## Run it

```sh
toolkit topics tag --demo     # tag a spread sample of clips → review diags/topics/<set>_demo.md
toolkit topics tag            # full corpus
toolkit topics thresholds     # decision aid for the rollup bar(s)
toolkit topics rollup         # clip tags → interview tags
```

`toolkit topics preview --clip <id>` prints the exact request for one clip. Demos include a
per-topic justification by default (off for full runs) — useful for judging borderline calls.

## Reviewing and tuning

Each clip is scored 0/1/2 per topic (0 = no, 1 = maybe, 2 = yes); a clip is "tagged" with a
topic at score 2. If topics are over- or under-applied, sharpen the `description` in your
spreadsheet and re-demo. The **rollup** decides when an interview gets a topic: either a flat
share-of-clips bar (`rollup: {scheme: flat, threshold_pct: 30}`) or rarity-binned bars that ask
more of common topics than rare ones (`scheme: binned`). `toolkit topics thresholds` shows the
trade-offs.

## Settings

`config.yaml` → `topics`: `model`, `reasoning`, `default_set`, `sets.<set>.{file, rollup}`.
`advanced/topics.yaml`: `score_values`, `justify_min_score`, `demo_n_clips`, `max_workers`,
`prompt`.

## Output

`outputs/topics/<set>_clip_topics_{wide,long}.parquet` (clip scores) and
`<set>_interview_topics_{wide,long}.parquet` (interview tags).
