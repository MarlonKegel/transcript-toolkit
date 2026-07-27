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

## Ask an AI about this toolkit

Rather than reading the docs, you can have ChatGPT, Claude or Gemini answer questions about them.
Paste this into a new chat:

```
Read the documentation at this link, then answer my questions about this toolkit:
https://raw.githubusercontent.com/MarlonKegel/transcript-toolkit/main/llms-full.txt
```

Then ask away — *"can I choose which interviews the demo runs on?"*, *"how do I add a second
topic list?"*, *"what does it cost to tag 800 clips?"*

That link is the entire documentation as one plain-text file. Give the assistant **that** link,
not the GitHub repo link: GitHub's pages are rendered with JavaScript and aren't in most search
indexes, so an assistant handed the repo URL will usually answer from general knowledge and get
the specifics wrong.

Offline, or want the docs for the version you actually have installed? Run **`toolkit docs`** —
it writes `transcript-toolkit-docs.md` into the current folder, ready to drag into a chat.

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
- [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) — when something goes wrong
- [llms-full.txt](llms-full.txt) — all of the above in one file, for AI assistants (see above)
