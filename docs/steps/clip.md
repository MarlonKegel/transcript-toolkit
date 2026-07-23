# clip

`toolkit clip` — split each interview into topically coherent **clips** (contiguous ranges of
paragraphs). Clips are the unit that `label`, `topics`, and `locations` work on.

## Run it (demo-first)

```sh
toolkit sample          # once: pick the demo interviews
toolkit clip --demo     # clip just those → review page opens in your browser
toolkit clip            # full corpus (after a demo of the current settings)
```

`toolkit clip preview` shows how each interview would be chunked (for long interviews) without
calling the API. `toolkit clip annotate` re-renders the review pages from existing results.

Clip is the one step with no Batch-API option: a long interview's chunks run in sequence, because
each chunk's prompt carries the previous chunk's clip decisions as locked context. They therefore
can't all be submitted up front the way the other steps' calls can.

## Reviewing

The demo opens `diags/clip/index.html` in your browser (on a Mac; elsewhere, double-click it).
It links one page per interview, each showing the transcript with clip boundaries marked. Judge
whether boundaries fall at real topic shifts and whether procedural chatter (scheduling, mic
checks) is separated out. To adjust, edit `prompts/segment_interview.md` or the chunking settings,
then re-demo.

## Settings

`config.yaml` → `clip`: `model`, `reasoning`. `advanced/clip.yaml`: `chunk_threshold_tokens`
(interviews above this are processed in overlapping chunks), `overlap_paragraphs`, `max_workers`,
`verbosity`, `prompt`.

## Output

`outputs/clips/clips.parquet` (one row per clip) and `outputs/clips/paragraphs_clipped.parquet`
(every paragraph with its clip id; procedural paragraphs marked). Interrupted runs resume — just
re-run.
