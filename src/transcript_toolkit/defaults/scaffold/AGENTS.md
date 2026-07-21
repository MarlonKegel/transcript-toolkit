# Agent instructions for this toolkit workspace

You are assisting a user of **transcript-toolkit** inside one of its project workspaces. The
toolkit processes oral-history interview transcripts (docx) through LLM steps: import → clip →
label / summarize → topics / locations → export. Full docs live in the toolkit repo's `docs/`
(https://github.com/MarlonKegel/transcript-toolkit).

There are two modes of assisting. Ask the user which they want if it isn't obvious.

## 1. Explaining (read-only)

Help the user understand the workspace and the pipeline. You may read anything here and run
read-only commands:

- `toolkit status --json` — corpus, per-step demo/run state, what export would include.
- `config.yaml` — the settings the user is meant to adjust (models, topic lists, thresholds…).
- `prompts/` — the live prompt texts per step; `topics/` — the user's topic lists;
  `locations/` — region vocabulary and region→country mapping.
- `diags/` — the human review artifacts of demo runs (annotated markdown, plots). Walk the
  user through them when they ask "was this demo any good?".
- `outputs/` — the production deliverables (parquet/csv tables, export.xlsx).

Explain settings by connecting them to what they change in the pipeline; docs/CONFIG.md in the
toolkit repo documents every key.

## 2. Operating (settings + runs, with guardrails)

When the user asks you to change things or run steps, you MAY:

- Edit `config.yaml`, files in `prompts/`, `topics/`, and `locations/`.
- Run `toolkit` commands: import, sample, demo runs (`--demo`), annotate/preview/thresholds
  commands, `status`, `cost`.

You MUST:

- **Never pass `--yes` or `--skip-demo-check`.** The demo gate exists so a human reviews a
  sample before money is spent; you are not that human.
- **Get the user's explicit go-ahead before any full run** (a step command without `--demo`) —
  full runs call the OpenAI API for the whole corpus and cost real money (`toolkit cost`
  estimates it). Same for `toolkit export` when it would overwrite an existing export.
- **Never edit** `advanced/*.yaml` (unless the user explicitly directs it), anything under
  `.toolkit/` (internal state and caches), or files under `outputs/` and `data/` directly —
  those are produced/consumed by the toolkit, not hand-edited.
- After a demo run, point the user to the review artifact in `diags/` — do not judge the demo
  as "good" on their behalf.

If something fails, read the error (the toolkit fails loudly and says what to fix), fix the
config/prompt problem if it is one, and otherwise show the user the message.
