# The workflow, end to end

The pipeline (after [setup](SETUP.md) and `toolkit import`):

```
import ─► clip ─► label ──────────┐
   │        └──► topics ──────────┤
   │        └──► locations ───────┼─► export (xlsx)
   └───────► summarize ───────────┘
```

`clip` must run before `label` / `topics` / `locations`; those three are independent of each
other; `summarize` only needs `import`. `export` includes whatever has been produced so far.

## Demo-first: how every LLM step is run

Each LLM step costs real money on a full corpus and its behavior depends on prompts and
settings you can tune. So every step follows the same loop, and the toolkit **enforces** it:

1. **Demo** — run the step on a small sample: `toolkit <step> --demo`
   (for clip/label the sample is the interviews drawn once by `toolkit sample`; topics and
   locations sample clips automatically). You can demo the steps in sequence — `label --demo`
   works off `clip --demo`, so you can review the whole pipeline on a few interviews before
   committing to a full run of anything.
2. **Review** — the demo opens a review page in your browser (a self-contained `.html` file in
   `diags/<step>/` — on a Mac it opens automatically; elsewhere, double-click it). Judge the
   output: are clip boundaries sensible, labels sharp, tags right?
3. **Adjust** — edit `config.yaml` (models, thresholds), the step's prompt in `prompts/`
   (`toolkit status` names the file each step reads), or your topic list, and go back to 1. Every
   demo is cheap, and repeated runs re-use everything already computed.
4. **Full run** — `toolkit <step>` (no flags). This only starts if a demo of the *current*
   prompt+settings has been made (otherwise it tells you what changed), asks you to confirm the
   spend (see below), and then processes the whole corpus. Results land in `outputs/`, review
   files in `diags/`.

The app ([APP.md](APP.md)) runs this exact loop: each step page's *Try it* → read the review
pages → adjust or *run on everything* are these four moves, enforced the same way.

### If a step seems stuck

Occasionally one API call stops responding while the rest finish — you'll see progress reach,
say, 134 of 136 and then sit there. **Press Ctrl-C (more than once if it doesn't stop the first
time), then run the exact same command again.** It picks up where it left off and usually
completes immediately.

Nothing is lost and nothing is paid for twice: every finished call is written to the cache as it
completes, so a re-run only redoes what was still missing. The same is true after a laptop sleep,
a dropped network, or a crash — the fix is always "run it again".

A call that is merely slow now says so (`still waiting on a gpt-5.6-sol call (94s elapsed)`), so
silence for more than a minute or two is the signal to interrupt.

## Run now, or run cheap? (the Batch API)

Demos always run immediately. On a **full run**, the confirmation asks how to send the work, with
both prices worked out from your own demo:

```
Tag 801 clip(s) with gpt-5.6-luna (0 already cached, 801 fresh call(s)).
  [1] Run now       ~$4.30   results in this session
  [2] Batch API     ~$2.15   50% cheaper, up to 24h turnaround
  [n] Cancel
Choose [1/2/n]
```

Pick **[1]** when you want the results now — that's the normal choice. Pick **[2]** when the run
is large and you can wait: OpenAI's Batch API is half price but has no speed guarantee (often
much faster than 24h, but don't count on it). A batch job is resumable — press Ctrl-C and re-run
the same command later and it re-attaches to the same job rather than paying again.

Skip the question with `--batch` or `--no-batch`; `--yes` runs immediately without asking.
Available on `label`, `summarize`, `topics tag` and `locations tag`. **Not** on `clip`: its chunks
are sequential within an interview (each chunk's prompt is built from the previous chunk's
result), so they can't all be submitted up front.

## A typical project, in commands

```sh
toolkit import                 # parse transcripts; check the printed tables
toolkit sample                 # pick the demo interviews (once)

toolkit clip --demo            # demo → review page opens → adjust → re-demo
toolkit clip                   # full corpus
toolkit label --demo           #   (same loop)
toolkit label

toolkit summarize --demo
toolkit summarize

#   transcripts with no timestamps at all can be summarized and nothing else. Put them in
#   data/unsynced/ (see docs/steps/import.md); their summaries join the ones above.
toolkit import --unsynced
toolkit summarize --unsynced --demo
toolkit summarize --unsynced

#   drop your topic list into topics/ first (collection.xlsx or .csv: name, description)
toolkit topics tag --set collection --demo    # → review page opens → tune the list → re-demo
toolkit topics tag --set collection
toolkit topics thresholds --set collection    # compare how tags could be decided → a review page
toolkit topics rollup --set collection        # apply it: clip tags → interview tags

toolkit locations tag --demo   # works out of the box (built-in region list)
toolkit locations tag
toolkit locations map          # regions → countries
toolkit locations thresholds   # compare how tags could be decided → a review page
toolkit locations rollup       # apply it: clip tags → interview tags

toolkit export                 # one xlsx in outputs/ with everything so far
toolkit status                 # where things stand, and what each step is waiting for
toolkit cost                   # what has been spent so far
```

## Cost expectations

Rough production figures from the project this toolkit grew out of (35 interviews, ~800
clips): clipping ≈ a few dollars; labels ≈ a few dollars; summaries well under a dollar;
topic tagging ≈ $2–3 per taxonomy; location tagging ≈ $3 (half with `--batch`). `toolkit cost
--to-n N` extrapolates from your own demo runs.

## Where things live

| Folder | What | Do you edit it? |
|---|---|---|
| `config.yaml` | the settings meant to be adjusted | yes |
| `advanced/` | everything else tunable | rarely |
| `prompts/`, `topics/`, `locations/` | prompt texts, topic lists, region vocabulary | yes |
| `data/` | your transcripts + the imported dataset | you add files |
| `outputs/` | deliverables (tables + export.xlsx) | never by hand |
| `diags/` | review pages (`.html`) from demos and runs | open them in a browser |
| `.toolkit/` | caches and run state | never |
