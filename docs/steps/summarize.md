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

This is the only step that can read a transcript with no timestamps — a summary is made from the
interview as a whole, so it needs none. Put those files in `data/unsynced/`, then:

```sh
toolkit import --unsynced          # parse them; see docs/steps/import.md
toolkit summarize --unsynced --demo
toolkit summarize --unsynced
```

They are bookkept separately from the collection — their own demo, their own record of having
run — because they are different transcripts and the demo is what you read before paying for the
rest. Their summaries land in the **same** `summaries.parquet`, with `synced: false`, and the
export's Interviews tab gains a **Transcript** column saying which is which. Those rows have a
summary and no tags, which is a fact about the transcript rather than unfinished work.

In the app: the Summarize page, under "Transcripts that were never SYNC'd".

## Output

`outputs/summaries/summaries.parquet` (one row per interview).
