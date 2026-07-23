# transcript-toolkit

Toolkit for processing oral history interview transcripts. Takes SYNC'd (timestamped) `.docx`
transcripts and produces, via LLM steps with human review built in:

```
import ─► clip ─► label ──────────┐
   │        └──► topics ──────────┤
   │        └──► locations ───────┼─► export (xlsx)
   └───────► summarize ───────────┘
```

- **import** — parse transcripts into a paragraph dataset
- **clip** — split each interview into topically coherent clips
- **label** — one-line label per clip
- **summarize** — a "scope and content" abstract per interview
- **topics** — score every clip against your topic list(s), roll up to interview tags
- **locations** — tag clips to countries/regions, roll up to interview tags
- **export** — one spreadsheet with everything produced so far

Every LLM step is **demo-first**: you run it on a small sample, review the annotated output in
`diags/`, adjust settings/prompts, and only then run the full corpus.

> Ported from the research working repo
> ([transcript_toolkit_working-repo](https://github.com/MarlonKegel/transcript_toolkit_working-repo))
> and verified against its production outputs: the paragraph dataset, both topic-set interview
> rollups, and the full locations map/rollup chain reproduce the originals exactly.

## Quickstart

```sh
# one-time install (see docs/SETUP.md for the full Mac walkthrough, incl. installing uv)
uv tool install git+https://github.com/MarlonKegel/transcript-toolkit.git

toolkit init my-archive && cd my-archive
#  → put your OpenAI key in .env, drop transcripts in data/
toolkit import
toolkit status
```

## Documentation

- [docs/SETUP.md](docs/SETUP.md) — install walkthrough (Mac)
- [docs/WORKFLOW.md](docs/WORKFLOW.md) — the demo-first pipeline, end to end
- [docs/steps/](docs/steps/) — one page per step
- [docs/CONFIG.md](docs/CONFIG.md) — every setting
- [AGENTS.md](AGENTS.md) — for coding agents working on this repo (each workspace also gets its
  own `AGENTS.md` for agent-assisted use)
