# Agent instructions — transcript-toolkit (developer tier)

This file is for coding agents working on the toolkit REPO itself. (Each project workspace
created by `toolkit init` carries its own `AGENTS.md` with rules for assisting end users.)

## Architecture

- `src/transcript_toolkit/cli.py` — argparse dispatch only; handlers are thin, logic lives in `steps/`.
- `project.py` — workspace resolution + `toolkit init` scaffolding; `state.py` — demo gate + run records.
- `core/` — shared building blocks (config merge, JSONL cache, ids, LLM calls, rendering, tables).
- `steps/` — one module/package per pipeline step; step functions take `(project, options)`,
  raise `ToolkitError`, never parse args or call `sys.exit`.
- `defaults/` — package data: default prompts, region vocabulary + mapping, pricing table, and
  the `scaffold/` templates copied by `toolkit init`.
- `app/` — `toolkit app`: a NiceGUI window onto this same CLI, on 127.0.0.1 only. It **never
  calls a step function**; every button runs the real `toolkit` command as a child process on a
  pty (`jobs.py`), which is why the CLI's own confirmation prompt and its own cost figures reach
  the user as buttons and no arithmetic is duplicated. One job at a time, server-side, so a run
  outlives the browser tab. `content.py` is the only place allowed to name a command or a flag —
  a test walks the real argparse parser and fails if it drifts. `pages/` is one module per page;
  `theme.py` holds the palette; `stage.py` answers "where has this project got to".
- `defaults/app/icon.png` — the Mac app icon, 1024×1024, already masked into the macOS rounded
  square with its margin (macOS does not round an app icon for you; `app/launcher.py` feeds this
  straight to `sips`/`iconutil`). It is **generated, not hand-drawn**, by the scripts in
  `~/projects/incite/brand/` — which live outside this repo because they carry the INCITE signet
  and its prompts. To change the icon, work there and re-run `install_icon.py N`; see
  `brand/README.md`. Nothing in this repo can regenerate it.

## Contracts (do not break)

- **Instruction byte-stability is load-bearing.** The per-call cache and the demo gate both key
  on the exact instructions text (prompt + injected taxonomy/regions). Generators of injected
  text must stay deterministic; any cosmetic change to assembled instructions invalidates user
  caches and demos. Golden cache-key tests guard this — if one fails, you changed call-shaping
  text; make sure that was intended.
- Expensive steps are idempotent + resumable via the append-only JSONL caches under the
  workspace's `.toolkit/cache/`; subset runs merge into deliverables, never overwrite them.
  **One record in a cache = one call that was paid for**, which is what makes `toolkit cost`
  (and the app's project cost report) a statement about money rather than an estimate.
- **A workspace's `config.yaml` is edited as text, never round-tripped.** Its comments are the
  documentation of every setting and the app shows them verbatim (`core/settings.py`), so a
  yaml load/dump would delete the user's documentation. `settings.save` re-reads what it wrote
  and refuses unless exactly the named keys changed.
- Two path conventions that are easy to conflate: a **prompt name** is relative to `prompts/`
  (`clip_interview.md`), an **addendum path** is relative to the workspace
  (`prompts/prompt_addendums/house.md`, resolved by `steps/label` from the project root).
  `core/prompts.py` owns both and is the only place that should answer "which file?".
- Deliverables have fixed filenames under `outputs/`; model/reasoning metadata lives in table
  columns and `.toolkit/state.json`, not filenames.

## Style (owner's rules)

- Simple, fail-loud, single-purpose. No speculative error handling or silent fallbacks.
- Tunables live in the scaffold's `config.yaml` / `advanced/*.yaml`, never hardcoded.
- Keep code DRY once stable; shared logic goes in `core/`.
- Git: always commit with a message; **never add Claude (or any AI) as co-author**.

## Testing

```sh
pip install -e .[dev]
pytest -q
```

Fixtures are tiny synthetic docx under `tests/fixtures/` — never add real transcripts, prompts
containing personal data, secrets, or `.env` files to this repo.
