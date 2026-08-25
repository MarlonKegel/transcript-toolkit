# summarize

`toolkit summarize` — a short "scope and content" abstract for each interview. Independent of
clipping; needs only `import`.

## Run it

```sh
toolkit summarize --demo   # summarize a couple of interviews → review page opens in your browser
toolkit summarize          # all interviews
```

By default a narrator's sessions are pooled into one summary; `--no-pool-sessions` (or
`summarize.pool_sessions: false`) summarizes each session file separately. A full run asks whether
to run now or on the 50%-off [Batch API](../WORKFLOW.md#run-now-or-run-cheap-the-batch-api).

## Reviewing

`diags/summarize/summaries.html` lists each summary with its length (the demo opens
`demo_summaries.html` for you). Check for accuracy (nothing invented),
coverage of the main through-lines, and length. Tune the tone/length in
`prompts/summarize_interview.md`.

## Settings

`config.yaml` → `summarize`: `model`, `reasoning`, `pool_sessions`. `advanced/summarize.yaml`:
`verbosity`, `max_workers`, `demo_n`, `prompt`.

## Transcripts that were never SYNC'd

They are summarized along with everything else — they are part of the collection (see
[import.md](import.md)). `toolkit summarize --unsynced` picks out just those, the way
`--interview` picks out a few named ones, which is useful when you have added some and do not
want to walk the whole collection again.

The Interviews tab of the export marks them, so a reader can see why those rows' clips carry no
times.
