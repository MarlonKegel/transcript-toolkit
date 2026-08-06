# label

`toolkit label` — give each clip a one-line label (a short declarative phrase, like a chapter
title). Needs `clip` to have run.

## Run it

```sh
toolkit label --demo    # label the sample's clips → review page opens in your browser
toolkit label           # full corpus
```

`toolkit label preview` shows the grouping (labels are produced several clips at a time, with
neighbouring clips shown as read-only context so labels stay distinct — that grouping is about how
many clips share one request, and is unrelated to the Batch API below). `toolkit label annotate`
re-renders the review pages. A full run asks whether to run now or on the 50%-off
[Batch API](../WORKFLOW.md#run-now-or-run-cheap-the-batch-api).

## Reviewing

`diags/label/index.html` links one page per interview showing each clip with its label (the demo
opens it for you). Check that labels are specific, distinct, and
in your house style. For project-wide consistency rules (e.g. "always write UNHCR, never the UN
Refugee Agency"), put them in a file and point `config.yaml` → `label.addendum` at it (e.g.
`prompts/prompt_addendums/label_addendum.md`); the text is appended to the label prompt.

## Fixing a label by hand

Sometimes one label needs one word changed, and re-prompting the model over it is the wrong
tool. Three ways to fix it yourself, all landing in **`label_overrides.csv`** at the workspace
root:

- **In the review page** (app only): an *edit* control sits next to each label — change it
  right where you read it. Labels you fixed are marked *edited by hand*.
- **In the exported sheet**: edit the Label column of `outputs/export.xlsx`; the next
  `toolkit export` notices the difference against what it wrote last time and keeps your
  version instead of overwriting it. Editing a cell back to the model's own words lifts the
  override again.
- **In the file itself**: `label_overrides.csv` is a plain table (`clip_id,label,...`) you can
  edit in any editor.

The model's own labels in `outputs/labels/` are never rewritten — your version is laid over
them wherever labels are shown or exported. An override is pinned to its clip's span, so if the
clip itself changes (a corrected transcript is re-imported, or clip boundaries move), the
override is dropped with a printed warning rather than silently applied to different text.

## Settings

`config.yaml` → `label`: `model`, `reasoning`, `addendum`. `advanced/label.yaml`:
`batch_threshold_tokens`, `max_workers`, `verbosity`, `prompt`.

## Output

`outputs/labels/labels.parquet` (the clips table plus a `label` column).
