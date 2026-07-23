# label

`toolkit label` — give each clip a one-line label (a short declarative phrase, like a chapter
title). Needs `clip` to have run.

## Run it

```sh
toolkit label --demo    # label the sample's clips → review page opens in your browser
toolkit label           # full corpus
```

`toolkit label preview` shows the batching (labels are produced several clips at a time, with
neighbouring clips shown as read-only context so labels stay distinct). `toolkit label annotate`
re-renders the review pages.

## Reviewing

`diags/label/index.html` links one page per interview showing each clip with its label (the demo
opens it for you). Check that labels are specific, distinct, and
in your house style. For project-wide consistency rules (e.g. "always write UNHCR, never the UN
Refugee Agency"), put them in a file and point `config.yaml` → `label.addendum` at it (e.g.
`prompts/label_addendum.md`); the text is appended to the label prompt.

## Settings

`config.yaml` → `label`: `model`, `reasoning`, `addendum`. `advanced/label.yaml`:
`batch_threshold_tokens`, `max_workers`, `verbosity`, `prompt`.

## Output

`outputs/labels/labels.parquet` (the clips table plus a `label` column).
