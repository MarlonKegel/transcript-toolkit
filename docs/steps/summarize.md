# summarize

`toolkit summarize` — a short "scope and content" abstract for each interview. Independent of
clipping; needs only `import`.

## Run it

```sh
toolkit summarize --demo   # summarize a couple of interviews → review diags/summarize/
toolkit summarize          # all interviews
```

By default a narrator's sessions are pooled into one summary; `--no-pool-sessions` (or
`summarize.pool_sessions: false`) summarizes each session file separately.

## Reviewing

`diags/summarize/*.md` lists each summary with its length. Check for accuracy (nothing invented),
coverage of the main through-lines, and length. Tune the tone/length in
`prompts/summarize_interview.md`.

## Settings

`config.yaml` → `summarize`: `model`, `reasoning`, `pool_sessions`. `advanced/summarize.yaml`:
`verbosity`, `max_workers`, `demo_n`, `prompt`.

## Output

`outputs/summaries/summaries.parquet` (one row per interview).
