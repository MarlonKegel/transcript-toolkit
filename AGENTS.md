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

## Contracts (do not break)

- **Instruction byte-stability is load-bearing.** The per-call cache and the demo gate both key
  on the exact instructions text (prompt + injected taxonomy/regions). Generators of injected
  text must stay deterministic; any cosmetic change to assembled instructions invalidates user
  caches and demos. Golden cache-key tests guard this — if one fails, you changed call-shaping
  text; make sure that was intended.
- Expensive steps are idempotent + resumable via the append-only JSONL caches under the
  workspace's `.toolkit/cache/`; subset runs merge into deliverables, never overwrite them.
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
