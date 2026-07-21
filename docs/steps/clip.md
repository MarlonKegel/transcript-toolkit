# clip

`toolkit clip` — split each interview into topically coherent **clips** (contiguous ranges of
paragraphs). Clips are the unit that `label`, `topics`, and `locations` work on.

## Run it (demo-first)

```sh
toolkit sample          # once: pick the demo interviews
toolkit clip --demo     # clip just those → review diags/clip/*.md
toolkit clip            # full corpus (after a demo of the current settings)
```

`toolkit clip preview` shows how each interview would be chunked (for long interviews) without
calling the API. `toolkit clip annotate` re-renders the review markdown from existing results.

## Reviewing

Open the per-interview files in `diags/clip/`: each shows the transcript with clip boundaries
marked. Judge whether boundaries fall at real topic shifts and whether procedural chatter
(scheduling, mic checks) is separated out. To adjust, edit `prompts/segment_interview.md` or the
chunking settings, then re-demo.

## Settings

`config.yaml` → `clip`: `model`, `reasoning`. `advanced/clip.yaml`: `chunk_threshold_tokens`
(interviews above this are processed in overlapping chunks), `overlap_paragraphs`, `max_workers`,
`verbosity`, `prompt`.

## Output

`outputs/clips/clips.parquet` (one row per clip) and `outputs/clips/paragraphs_clipped.parquet`
(every paragraph with its clip id; procedural paragraphs marked). Interrupted runs resume — just
re-run.
