# Worked example — OSF Oral History

The real configuration of the archive this toolkit was built for, as a reference when setting up
your own project. Nothing here runs on its own; copy the parts you need into your workspace.

## Files

- `config.yaml` — a filled-in project config: interviewer labels, two topic sets (a broad
  8-topic **collection** and a fine 36-topic **filter**, each with its own rollup scheme), and
  location relabeling/place-tags tuned for this corpus.
- `topics/collection.xlsx`, `topics/filter.xlsx` — the two topic lists in the format
  `toolkit topics` expects (`id`, `name`, `description`). Open them to see how much detail a good
  topic `description` carries — that text is what the model reads to decide whether a clip
  belongs.
- `label_addendum.md` — project-specific labeling rules (naming conventions) referenced by
  `label.addendum`.

## Things worth copying from this example

- **Two topic sets** tagged independently: point `--set collection` / `--set filter` at each.
- **Rollup rules chosen per list**: the broad collection uses one flat 30% bar; the sparse
  36-topic filter uses rarity bins, where a rare topic gets a lower share-of-clips threshold
  than a common one. Both were picked by reading `toolkit topics thresholds --set <name>`, which draws
  what each rule would tag.
- **Location canon**: `relabel` fixes model spelling variants and merges (e.g. Israel + Palestine
  into one tag); `place_tags` keeps subnational places (Chechnya, Crimea) as their own tag.
- **Descriptions matter**: the filter topics are tagged only on a *specific, substantive* mention
  — that instruction lives in the topic descriptions and the prompt, not in code.
