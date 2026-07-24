# Troubleshooting

The toolkit fails loudly: when something is wrong it stops and prints what to fix. Common cases:

**"OPENAI_API_KEY not set"** — put your key in the workspace's `.env` file
(`OPENAI_API_KEY=sk-...`). Ask your admin for a key.

**"Not inside a toolkit workspace"** — run the command from inside your project folder (the one
`toolkit init` created), or pass `--project /path/to/project`.

**A run stopped partway (laptop slept, network dropped, you hit Ctrl-C).** Nothing is lost. Run
the exact same command again — every completed call is cached and won't be paid for twice; it
picks up where it stopped.

**"No demo run recorded" / "the demo … is stale".** A full run needs a demo of the *current*
settings first. Run the step with `--demo`, review the file it points to in `diags/`, then run
the full command. "Stale" means you changed a prompt, model, or setting since the last demo — so
re-demo to see the effect before spending on the whole corpus.

**Import: my interviewer shows up as "Narrator".** Set `import.interviewer_labels` in
`config.yaml` to the label(s) your interviewer uses (e.g. `[Q, Q1]`) and re-run `toolkit import`.

**Import: "No parsable paragraphs" / a file is rejected.** That transcript isn't in the expected
`[HH:MM:SS] SPEAKER: text` format (see [steps/import.md](steps/import.md)). It probably isn't a
SYNC'd transcript.

**Import: "Two transcripts yield the same interview id".** Two filenames collapse to the same id
after stripping suffixes. Rename one.

**Location tagging seems to add or drop places.** Tune the prompt (`prompts/tag_locations.md`)
and re-demo, or edit the region vocabulary in `locations/regions.yaml`. The `map` step only
knows regions listed in `locations/region_to_country.csv` — it will tell you if a tagged region
is missing from the mapping.

**`toolkit locations survey` won't run.** It needs extra software:
`pip install "transcript-toolkit[survey]"`, then `python -m spacy download en_core_web_trf`, and
a GeoNames dump (the command prints the exact download link and where to put it). The survey is
optional — you don't need it unless you're building a custom region list.

**A Batch API run (`--batch`) is taking a long time.** Batch jobs are cheaper (half price) but
run on OpenAI's own schedule — usually minutes, occasionally up to a day. It's resumable: re-run
the same command to check on it; you won't be double-charged.

**The export's tag columns aren't dropdowns in Excel.** Expected — see
[steps/export.md](steps/export.md). xlsx can't store multi-select validation.

**How much have I spent?** `toolkit cost` (all steps) or `toolkit cost <step>`. Each line is
priced at the transport it actually used — `sync` or `batch` — so the total is money spent, not a
hypothetical; a closing line tells you what the synchronous part would have cost on the Batch API.
`--to-n N` extrapolates a demo's per-call cost to a full run of N calls, and quotes both
transports (you haven't picked one for that run yet).
