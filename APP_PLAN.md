# Plan: `toolkit app` — local web GUI + Mac launcher

> Working document. Lives on the `app` branch only — never on `main`, which is what
> colleagues install from. Delete or fold into docs/ when the app ships.
> Read AGENTS.md first for repo conventions. File:line references were verified against
> commit `c0e7d29` (v0.1.8, 256 tests green).
>
> **Status: phases A–D built and reviewed** (branch `app`, 361 tests green, CI green).
> Phase E — merging to main, rewriting SETUP.md, the LICENSE decision, and the colleague
> cold-start test — is deliberately not done: it needs the Mac checklist in §9 and Marlon's
> sign-off. See §14 for what was built, §15 for what the review round found and fixed.

## 0. What is already decided and proven

**Product decision (made by Marlon):** build a GUI app on top of the CLI. The CLI stays fully
usable standalone; the app is a veneer over it. No hosting, no code signing, no Apple
Developer account, no .app downloads from GitHub.

**Architecture decision (research + smoke test, July 2026):**

- The app is a **NiceGUI local web server** inside the existing package, started by a new
  `toolkit app` command. Users keep installing/updating via uv exactly as today.
- Daily entry point is a **launcher .app generated locally on the user's Mac** by the toolkit
  itself. Locally created files carry no quarantine attribute, so Gatekeeper never fires —
  this sidesteps the unsigned-app wall macOS 15/26 built for *downloaded* apps.
- Rejected after research: downloadable .app (Gatekeeper "damaged"/Move-to-Trash flow repeats
  on every update without a $99/yr Apple Developer account), native wrappers
  (Tauri/Electron/pywebview-as-.app — same wall + toolchain rot), all hosted options
  (HF Spaces now paywalled per-seat, ephemeral disk kills resume state, transcripts are
  IRB-sensitive), Streamlit/Gradio (jobs die with the browser tab — open unresolved issues).

**Smoke test — PASSED on the target hardware** (2023 MBP, macOS 26.5.2 (25F84), 2026-07-28).
Every load-bearing mechanic is now empirical fact, not theory:

| Verified | Evidence |
|---|---|
| osacompile + custom icns + ad-hoc codesign .app launches from Finder with **zero dialogs** | user run |
| Custom icon actually displays (Assets.car removal works on 26.5) | "It has a blue icon" |
| Detached server outlives the applet | pid 23057 alive after applet quit |
| Server survives lid-close sleep (509 s gap) and resumes, HTTP included | check2 all PASS |
| Localhost HTTP + browser auto-open, no Local Network / firewall prompt | tab opened itself |
| TCC prompt is **one-time**, correctly attributed to the app's own name ("ToolkitSmokeTest"), and access works after Allow | user saw exactly one dialog |
| Single-instance guard: second double-click does nothing | server.log "second launch refused" |
| Finder-launched context has bare launchd PATH (`/usr/bin:/bin:/usr/sbin:/sbin`) — absolute paths are mandatory | applet.log |

The verified launcher recipe lives in `scripts/mac_launcher_smoke_test.sh` — treat it as the
reference implementation for §5 and delete it in Phase E.

## 1. Architecture overview

```
Transcript Toolkit.app          (generated locally, ~/Applications, blue icon)
  └─ do shell script "'<abs>/toolkit' app --from-launcher >> <log> 2>&1 &"   then quits
       └─ toolkit app           (new CLI command)
            ├─ another instance already healthy?  → just open browser tab, exit
            └─ else: start NiceGUI server on 127.0.0.1:<PORT>, open browser
                 ├─ read-only, in-process:  gather_status(), config read/write,
                 │    taxonomy listing, cost estimates, diags serving
                 └─ anything that writes or spends money: SUBPROCESS
                      `toolkit <step> ... --yes --batch/--no-batch [--project DIR]`
                      stdout streamed live to the UI; cancel = SIGINT (= Ctrl-C,
                      already documented-safe: idempotent resume)
```

**The core insight from the interaction map:** every blocking prompt lives in
`core/console.py` (`confirm_or_abort` :21, `choose_transport` :45), and all five
money-spending steps already accept `yes`, `batch`, `skip_demo_check`, `demo`, `interviews`
parameters (`clip/run.py:446`, `label/run.py:260`, `summarize.py:84`, `topics/tag.py:134`,
`locations/tag.py:153`). The GUI collects the decisions *before* launching and passes
explicit flags — no mid-run stdin, no console refactor, CLI behavior untouched.

**Why subprocess instead of in-process step calls (decided, with rationale):**

1. **Cancel works.** Python threads can't be killed; a subprocess takes SIGINT, and the CLI
   already handles KeyboardInterrupt gracefully (`cli.py:445`, exit 130, "finished calls are
   cached"). The GUI Stop button becomes trivially correct because every step is resumable.
2. **Crash isolation.** A step OOM/segfault can't take the server down mid-conversation.
3. **Clean log capture.** Steps print() from many worker threads (`as_completed` loops,
   `llm.py:103` heartbeats). A subprocess pipe serializes that for free; in-process capture
   would need a process-global stdout tee with thread interleaving.
4. **DRY.** The CLI remains the single execution path; the app cannot drift from it.

In-process is reserved for fast, read-only calls: `gather_status(project)`
(`steps/status.py:40` — returns the dict, never prints), config/YAML loading,
`available_sets`/`discover_topic_files` (`taxonomy.py:55`, `:42`), pricing/cost estimation,
and serving `diags/` HTML.

## 2. New code layout

```
src/transcript_toolkit/app/
├── __init__.py
├── server.py        # ui.run() setup, port/lock handling, --from-launcher flag plumbing,
│                    # workspace switching, static /diags mount
├── jobs.py          # JobManager: one active subprocess, ring-buffer log, state machine
│                    # (idle → running → succeeded/failed/stopped), reattach on page load
├── workspaces.py    # registry of known workspaces (see §7), open/create/validate
├── launcher.py      # macOS launcher generation (osacompile/icns/PlistBuddy/codesign)
├── content.py       # step metadata: display names, descriptions, argv builders, which
│                    # flags each step takes (single source for all step pages)
└── pages/
    ├── home.py      # dashboard: pipeline state cards from gather_status()
    ├── setup.py     # workspace create/open, API key into .env, drag-drop .docx, import
    ├── step.py      # ONE parameterized page template for clip/label/summarize/topics/
    │                # locations: demo button, run dialog, live log, diags links
    ├── topics.py    # topic-set management extras (upload csv/xlsx, set picker)
    ├── export.py    # export + reveal in Finder
    └── settings.py  # config.yaml editing, update check/run, version info
```

New package data: `defaults/app/icon.png` (real 1024×1024 icon, to be produced — see
decisions) and `defaults/app/launcher.applescript.template`.
**pyproject gotcha:** `package-data` globs are per-directory, not recursive
(`pyproject.toml` — a new `defaults/app/` line is required or the files silently won't ship).

## 3. Changes to existing code (all small, all listed)

1. **`cli.py`**: add `app` subcommand (`--port`, `--no-browser`, `--from-launcher`,
   `--install-launcher`, `--project`). Lazy-import `app.server` so plain CLI use never pays
   the NiceGUI import cost.
2. **`steps/import_.py`**: refactor `_print_summary` (:139) so the speaker-role and
   narrator-pooling tables are *built* by a public function returning plain data
   (e.g. `import_summary(df, session_regex, regimes, ...) -> dict`) and *printed* by the CLI
   wrapper. The GUI renders the same dict as tables. `tests/test_import.py:65` scrapes
   stdout — keep printed output byte-identical.
3. **`steps/locations/tag.py:155`**: fix the `batch: bool = False` annotation to
   `bool | None = None` (behavioral no-op — CLI already passes None — but the app's argv
   builder relies on uniform semantics).
4. **`state.py` demo-gate messages** (:76, :81) embed CLI commands ("Run `toolkit clip
   --demo`…"). Keep them; the GUI maps the ToolkitError message to a "Run demo" button by
   step key, showing the original text as detail.
5. **`core/update.py`**: no changes needed — `run_update()` (:87) and `update_notice()`
   (:67) are already GUI-callable.
6. **`pyproject.toml`**: add `nicegui==<current exact>` to base dependencies (decision 11.4),
   add `defaults/app/*` package-data line. **Keep matplotlib** — it is lazy-imported inside
   functions (`steps/locations/thresholds_aid.py:80`, `steps/topics/thresholds_aid.py` same
   pattern) to draw the thresholds figures; a top-level grep misses it. Do not remove.
7. **`docs/`**: Phase E only (keep the repo quiet until ship): new `docs/APP.md`,
   SETUP.md gains the launcher step, README quickstart mentions the app; regenerate the docs
   bundle (`scripts/build_docs_bundle.py`) — CI fails otherwise (`ci.yml` runs `--check`).

Everything else is additive under `src/transcript_toolkit/app/`.

## 4. Job model (jobs.py) — the part to get right

- **One job at a time, globally.** The pipeline is sequential by nature; a second Run click
  while a job is live shows "a run is already in progress" with a link to its log. Enforced
  in JobManager, not the UI.
- Job = `{id, step_key, argv, workspace_root, started_at, state, returncode, log: deque(maxlen≈5000)}`.
  Spawn with `asyncio.create_subprocess_exec(sys.executable, "-m", "transcript_toolkit.cli", ...)`
  — NOT the `toolkit` shim, so the job always runs the same code as the server. Set
  `TOOLKIT_NO_OPEN=1` in the child env (`console.py:11` respects it) so demo runs don't pop
  browser windows/Finder from a background process; the GUI links the diag itself. Merge
  stderr into stdout order (`stderr=STDOUT`).
- Stream lines into the deque; UI page holds a `ui.log` (or similar) refreshed by a timer
  reading from the deque — **reattach is free**: any new page load renders the deque and the
  current state. This is the tab-close-and-reopen requirement, solved by server-side state.
- **Stop button** sends SIGINT once; escalate to SIGKILL only after a generous timeout
  (e.g. 30 s) and say so. UI copy after stop: "Stopped. Finished calls are cached — running
  the step again picks up where it left off." (mirrors `cli.py:447`).
- Exit code 2 + ToolkitError text on the pipe = expected failure → render the message
  prominently (it is written for humans and already names the fix); exit 130 = stopped;
  anything else = unexpected, show full tail + "copy log" button.
- Persist nothing across server restarts in v1 (a restart with a live child orphans the
  child; the child finishes and caches its work, and the next status/gather call reflects
  it — acceptable because everything is resumable; documented as a known limitation).

**Run dialog flow (full run):**
1. User clicks "Full run" → GUI shows the spend dialog *before* spawning: unit count and
   cost estimate for sync vs batch, radio `Run now / Batch API (50% off, up to 24h)`,
   Cancel. Estimates come from the same machinery the CLI uses — expose a small pure
   function in `core/cost.py` if the existing `estimate_pair` needs glue; do NOT parse
   stdout for numbers.
2. Confirm → spawn with `--yes` + `--batch`/`--no-batch`.
3. Demo-gate refusal surfaces as the ToolkitError path above with a one-click "Run demo".

**Prerequisite errors the GUI must map to buttons, not just display** (grep for the exact
strings): the demo-gate messages (`state.py:76`, `:81` → "Run demo" button) AND
`core/sampling.py:70` "No demo sample drawn yet. Run `toolkit sample` first" → a
"Draw demo sample" button that runs `toolkit sample` as a subprocess. Sample is a hard
prerequisite for clip/label demos and appears nowhere else in the GUI otherwise — without
this mapping the journey dead-ends at the very first demo click. (Whether to auto-run
sample before the first demo instead is decision 11.13.)

**Batch runs and the one-job lock:** a Batch API run can pend up to 24 h, locking the GUI's
single job slot. That's the right v1 trade, but the UI copy for a pending batch job must
say: Stop is safe — the batch keeps processing at OpenAI, and re-running the step later
re-attaches to it without paying again (this is existing CLI behavior). Document
"GUI is single-tracked while a batch waits" as a known v1 limitation.

## 5. Launcher (launcher.py) — port of the verified recipe

`toolkit app --install-launcher` (idempotent, macOS-only, fail loudly elsewhere):

1. Resolve the absolute shim path: `shutil.which("toolkit")` from the *current* process env;
   fall back to `uv tool dir --bin`. Bake it into the applet — Finder launches see only
   `/usr/bin:/bin:/usr/sbin:/sbin` (verified).
2. Render `launcher.applescript.template`:
   `do shell script "'<abs>/toolkit' app --from-launcher >> '<log>' 2>&1 &"` with
   try/on error display alert (exact pattern in the smoke-test script; note the single
   quotes around paths).
3. `osacompile -o "~/Applications/Transcript Toolkit.app"`, PlistBuddy set/add
   `CFBundleIdentifier org.incite.transcript-toolkit` + `CFBundleName Transcript Toolkit`,
   icon: packaged PNG → `sips` iconset → `iconutil` → replace `Resources/applet.icns`,
   `rm Resources/Assets.car`, `touch`, then **`codesign --force -s -` last** (Apple Silicon
   refuses modified-after-signing bundles — verified fatal-if-skipped).
4. Print where it landed + "drag it to your Dock if you like".
5. Launcher log: `~/.cache/transcript-toolkit/app-launch.log`, tiny, overwritten per launch.

Regenerating the launcher changes its cdhash → macOS may re-ask the one Documents/Desktop
permission once. Harmless; document it.

`toolkit app` startup logic (server.py): probe `http://127.0.0.1:<port>/api/health` — if it
answers with our marker, open a browser tab at it and exit 0 (the double-click-twice path;
verified UX). **Version mismatch** (health reports an older version than this process, i.e.
after an update): tell the stale server to shut down via a loopback-only `/api/shutdown`,
then start fresh. If the port is occupied by a foreign process, fail loudly naming the port
and the fix: `toolkit app --install-launcher --port N` re-bakes the launcher with a
persistent alternate port (one guided Terminal command, once — decision 11.2).

**Server lifecycle:** the server runs until Mac shutdown or explicit quit. Settings page
gets a "Quit server" button (calls the same shutdown route). The update flow ends with:
"Update installed — click Quit server, then double-click the launcher again." Without this
control the post-update relaunch would silently reattach to the stale server.

## 6. Pages (concrete, mapped to existing functions)

| Page | Reads (in-process) | Runs (subprocess) |
|---|---|---|
| Home | `gather_status()` per workspace: docx count, imported/stale, per-step demo/full state + timestamps, deliverables | — |
| Setup | workspace registry; `.env` presence (never display the key, only "set/not set") | `toolkit import`; drag-drop copies .docx into `data/` first |
| Import results | refactored `import_summary()` dict: speaker-role table (the "is my config right?" moment), narrator pooling, timestamp regimes | re-run import |
| Each step page (template) | fingerprint/demo state from `gather_status`; links to `diags/<step>/index.html` served via static mount; last run info | `--demo`, full (spend dialog), `annotate`, `preview` |
| Topics | `discover_topic_files` / `available_sets`; upload .csv/.xlsx into `topics/` (auto-registration already exists: `taxonomy.py:114` writes config on next run) | `topics tag --set X`, rollup, thresholds |
| Locations | same pattern; thresholds/survey exposed but survey marked "advanced, needs [survey] extra" | locations tag/map/rollup/thresholds |
| Export | `LOCATION_MODES` choice, output path | `toolkit export --locations MODE`; then Reveal in Finder via `reveal()` (`console.py:11`) |
| Cost | cost breakdown (prefer a small structured function over parsing `run_cost` output) | — |
| Settings | config.yaml editor (see decision 11.3); version + `update_notice()`; Update button → `run_update()` subprocess → "Quit server, relaunch" instruction; Quit server button | `toolkit update` |

UI principles: one obvious "what's next" per state (the demo-first workflow *is* the
navigation); never hide the terminal command being run — show `$ toolkit label --yes ...`
above the live log so users learn the CLI passively and support-by-chat-assistant stays
possible.

## 7. Workspace handling

- Registry file `~/Library/Application Support/transcript-toolkit/workspaces.json` (macOS
  convention for machine state; put the launcher log beside it in `~/Library/Logs/` — keep
  the update-check cache where it already lives): list of `{path, name, last_opened}`.
  Stale entries WILL happen (Finder renames/moves): on open failure, show the error and a
  one-click "Remove from list" — never auto-prune, no silent fallbacks. Corrupt registry
  JSON fails loudly naming the file. Updated by the GUI on open/create. `init` does NOT
  write it (CLI stays
  side-effect-free on machine state; the GUI discovers CLI-created workspaces via
  "Open existing…" path entry, validated with `find_project(explicit=...)` —
  `project.py:74` already supports exactly this).
- "New workspace" in the GUI wraps `init_project(dest)` (`project.py:104`) under a chosen
  parent folder + name; then walks the user into API-key entry (append/replace
  `OPENAI_API_KEY=` line in `.env`) and .docx drop.
- Active workspace is server-side session state; switching re-mounts the diags static route.
- Workspaces under `~/Documents` are fine — verified one-time TCC prompt with the app's own
  name. Default suggestion stays `~/Documents` for familiarity.

## 8. Distribution, versioning, update

- Dependency: `nicegui==<exact current 3.x>` in base deps. Pin EXACT — verified that
  `uv tool install` ignores lockfiles and re-resolves on every fresh install
  (astral-sh/uv#7768), and NiceGUI ships occasional breaking minors. At final handoff
  release, pin ALL direct deps exactly (`==`) so a 2028 install resolves identically
  (decision 11.5).
- `toolkit update` already covers the app (same package). The GUI Update button runs it,
  then: "Quit server → double-click the launcher" (see §5 lifecycle). Auto-exec-restart is
  deliberately out of v1 (fragile; decision 11.7).
- **Branch discipline (critical — live repo):** colleagues install and update from git HEAD
  of `main`; any push there ships immediately. ALL Phase A–D work happens on a feature
  branch (e.g. `app`) pushed to GitHub for backup but never merged. `main` receives nothing
  until Phase E, which starts with the merge and does version bump + docs bundle + tag in
  the same landing. The repo-convention "always commit and sync" applies to the branch.
- Version bump + docs-bundle regeneration on every push to `main` resumes at Phase E.

## 9. Testing plan

**Unit (Linux-safe, runs in CI):**
- `launcher.py`: template rendering (absolute paths, quoting), argv of every subprocess the
  module would run (mock `subprocess.run`; never execute osacompile on Linux), fail-loud on
  non-macOS.
- `jobs.py`: spawn a trivial `python -c` child; state transitions, log capture, SIGINT stop,
  exit-code classification (0 / 2 / 130 / other). No NiceGUI needed.
- `workspaces.py`: registry round-trip, validation of non-workspace paths.
- `import_summary()` refactor: table dicts match what the CLI printed before (golden text).
- argv builders in `content.py`: every step's flag set matches the real parser — walk
  `build_parser()` like `scripts/build_docs_bundle.py:_walk_parsers` does, so a CLI change
  breaks the test, not the app.
- pyproject: `defaults/app/*` present in a built wheel (test with `importlib.resources`).

**UI tests:** NiceGUI ships a pytest harness (`nicegui.testing`, `User` fixture — verify
current API against the pinned version). Cover: home renders from a fixture workspace;
run dialog builds correct argv; log pane reattaches after simulated reload; ToolkitError
surface. Keep shallow — the logic lives in jobs/content, tested above.

**Manual on-Mac checklist (gate for shipping, ~1 hour):**
1. Fresh `uv tool install` → `toolkit app --install-launcher` → double-click → browser opens.
2. Create workspace in GUI under Documents (expect exactly one TCC prompt, app-named),
   drop fixture .docx, import, read tables.
3. Demo → diag opens in new tab (served, not `open`ed) → full run with spend dialog →
   Stop mid-run → re-run resumes (cache hit visible in log).
4. Batch path end-to-end on the nano/cheap model.
5. Lid-close during a full run; reopen; job still streaming (verified for the server; verify
   the *subprocess* too).
6. Second double-click while running (expect: focuses/opens tab, no second server).
7. `toolkit update` from the GUI on a deliberately older install.
8. Everything again on a colleague's Mac from SETUP.md alone, no help. **This is the real
   acceptance test.**

## 10. Implementation phases

- **A — skeleton (foundation for everything):** `app/` package, `toolkit app` command,
  pinned NiceGUI, health endpoint, single-instance logic, home page on `gather_status`,
  jobs.py with the trivial-child tests green. *Acceptance: `toolkit app` on Linux serves the
  dashboard for a fixture workspace; 256 existing tests untouched.*
- **B — run orchestration:** step-page template, run dialog + cost estimate, demo/full/
  annotate/preview subprocesses, live log + reattach, stop button, demo-gate UX.
  *Acceptance: full fake-pipeline clickthrough on fixtures with a stubbed `call_llm` via the
  subprocess (env-gated fake, or the nano-model live smoke).*
- **C — the rest of the surface:** setup/workspace/key flow, import page + `import_summary`
  refactor, topics/locations/export/cost/settings pages.
- **D — launcher + Mac polish:** launcher.py, `--install-launcher`, `--from-launcher`,
  real icon, on-Mac manual checklist items 1–7.
- **E — ship:** merge the `app` branch to main; docs — new APP.md, and **restructure**
  SETUP.md (don't append): Terminal steps 1–3 unchanged, new step 4 = install launcher +
  double-click, "the app walks you through workspace, key, transcripts"; current CLI steps
  4–6 move to a clearly-marked CLI-only path so the standalone CLI journey stays fully
  documented. README + bundle regen; remove `scripts/mac_launcher_smoke_test.sh`;
  commit-or-delete this APP_PLAN.md; settle LICENSE (decision 11.12); restore
  version-bump-per-push; exact-pin all deps (decision 11.5); colleague cold-start test
  (checklist item 8); tag release.

Phases A–C are fully developable and testable on the Linux box; D–E need the Mac.

## 11. Decisions still open (owner: Marlon) — with recommendations

1. **Command name**: `toolkit app` (recommended — matches "the app") vs `toolkit gui`.
2. **Port**: recommend a fixed uncommon default (e.g. 8377) + `--port`; health endpoint
   distinguishes our server from squatters. Alternative: ephemeral port + written portfile
   (more moving parts, breaks bookmarks).
3. **Config editing UX**: (a) form for blessed keys written via ruamel.yaml round-trip (new
   dep, preserves comments); (a′) same form, but written via targeted per-key TEXT edits —
   the repo already has this exact pattern, dependency-free and tested, in
   `register_topic_set` (`taxonomy.py:113`, which edits config.yaml as text precisely
   because yaml round-trips strip comments) — recommended; (b) guarded text editor with
   YAML validation; (c) v1 read-only + "edit the file". Pick before Phase C.
4. **NiceGUI as base dependency vs `[app]` extra**: base recommended — colleagues are the
   audience; an extra they must know about defeats the purpose. Cost: ~heavier install for
   pure-CLI users (acceptable).
5. **Exact-pin policy at handoff**: pin all direct deps `==` in the final release
   (recommended) vs keep ranges. Decide at Phase E.
6. **Icon**: someone must produce a real 1024×1024 PNG (the smoke-test blue square works but
   is a placeholder). Any preference/branding?
7. **In-app update UX**: v1 = Update button + manual relaunch (recommended); auto-restart
   via exec is deferred.
8. **Launcher install trigger**: explicit `toolkit app --install-launcher` + SETUP step
   (recommended), vs auto-offer on first `toolkit app`, vs during `init` (wrong scope —
   launcher is per-machine, workspaces are per-project).
9. ~~matplotlib removal~~ — CLOSED: keep it (lazy-imported for thresholds figures, §3.6).
10. **Job history persistence** (v1: none — is "last run" info from state.json enough?
    Recommended: yes).
11. **`TOOLKIT_YES` documentation**: exists but undocumented; the app uses explicit `--yes`.
    Recommended: leave undocumented.
12. ~~License~~ — DECIDED 2026-07-29: **MIT**. Standard text, replace LICENSE wholesale, and
    check README/pyproject for any "internal use" wording that contradicts it.
13. **Demo sample UX**: explicit "Draw demo sample" button (recommended — preserves the
    deliberate sample-once pedagogy from WORKFLOW.md) vs auto-running `toolkit sample`
    before the first demo.
14. **Single-tracked GUI during 24 h batch waits** (§4): accept as documented v1 limitation
    (recommended) vs allowing a second concurrent job for independent steps.

## 12. Must-test-on-hardware list (can invalidate design details, not the architecture)

- Subprocess (not just server) survival across lid-close sleep, and across the server being
  killed (orphan finishes and caches — expected, unverified).
- TCC when the *subprocess* (grandchild) reads Documents after launcher-started server —
  smoke test covered the detached-server case; the extra fork level should inherit
  attribution, unverified.
- `nicegui.testing` API shape at the pinned version (docs drift).
- Browser choice quirks: default-browser = Chrome vs Safari for `open http://…` and for
  drag-drop upload of .docx.
- osacompile applet on a future macOS 27 (colleague machines will upgrade; Eclectic Light
  reports no signals of change for local ad-hoc code, but re-run the smoke test once on 27
  beta if available before handoff).
- Port 8377 (or chosen) not colliding with common dev tools on colleagues' Macs.

## 13. Risks

| Risk | Mitigation |
|---|---|
| NiceGUI breaking change on a future reinstall | exact pin; upgrade only deliberately with the manual checklist |
| Server killed with job live → orphaned child | everything is resumable; status reflects cached work on next look; documented |
| Two workspaces, user confusion about "which one am I in" | workspace name always in the header; one active workspace per server |
| Blocking the event loop with an in-process pandas call | keep in-process calls to the listed read-only set; anything slow goes `run.io_bound` |
| Launcher regenerated → TCC re-prompt | one-time, app-named, documented |
| Colleague on Sonoma (macOS 14) | all mechanics used are ≥ Big Sur era; smoke test on 26 is the strict case; note in SETUP that 14+ is fine |

## 14. What was built (phases A–D), and where it departs from this plan

Commit `a6534d1` on branch `app`. 344 tests pass (was 256); the CLI is untouched in behaviour.

### Decisions taken (§11), so the build could proceed

Every recommended option was taken, except where noted. Reopen any of these — none is buried.

| # | Decision | Taken |
|---|---|---|
| 1 | Command name | `toolkit app` |
| 2 | Port | fixed **8377**, `--port` overrides, `--install-launcher --port N` bakes it in |
| 3 | Config editing | **(b) guarded text editor**, not (a′). Reason below. |
| 4 | NiceGUI | base dependency, pinned `==3.15.0` |
| 5 | Exact pins | deferred to Phase E, as planned |
| 6 | Icon | still the placeholder — the replacement is written but blocked on billing, §16 |
| 7 | Update UX | Update button + "Quit, then reopen"; a **Quit** button now exists (Settings) |
| 8 | Launcher install | explicit `toolkit app --install-launcher`, also a button in Settings |
| 10 | Job history | none persisted; state.json already carries last-run info |
| 11 | `TOOLKIT_YES` | left undocumented; the app never uses it |
| 12 | LICENSE | **MIT**, holder Marlon Kegel — written and in the wheel's metadata (6ff28b3) |
| 13 | Demo sample | explicit button, offered automatically when a run fails for want of one |
| 14 | Batch waits | accepted as a v1 limitation; the UI says stopping is safe |

**Decision 3 taken as (b), not the recommended (a′):** a form writing targeted text edits needs
a per-key map of config.yaml that would itself drift from the scaffold. The text editor
preserves every comment by construction (the user edits the file), refuses to save invalid
YAML with the parser's own message, and is ~20 lines. The scaffold's comments are what explain
each setting, so keeping the user in front of them is arguably the better teacher.

### The one architectural departure: the run dialog

**Planned:** the app computes a cost estimate before spawning, shows its own dialog, then runs
with `--yes --batch/--no-batch`.

**Built:** the app spawns the plain command on a **pseudo-terminal** and shows the CLI's own
confirmation prompt, with its own figures, as buttons.

Why: every step computes "how many calls are fresh" deep inside itself, after planning chunks
or rendering clips. A pre-run estimate meant either duplicating that arithmetic per step (five
copies to keep in sync, and a wrong number in front of a spend approval is the worst possible
bug) or adding a `--plan` mode to five steps' internals. The pty costs neither: the question a
user approves *is* the CLI's question, and it cannot drift. It also solves output buffering
(Python line-buffers to a terminal, block-buffers to a pipe), and it works unchanged for
`clip`'s different confirm and for any prompt added later.

Guarded by tests: `tests/test_app_content.py` builds `console.choose_transport`'s real prompt
and asserts the app still recognises it; `tests/test_app_jobs.py` drives that real function
through a real pty and answers it.

### Smaller departures

- **Pages register explicitly** (`register()` per page module, called by `server.build()`)
  rather than by import side effect. Needed for NiceGUI's test harness, better regardless.
- **No `import_summary()` refactor of the print path.** `_print_summary` was left byte-identical
  (a test scrapes its stdout); instead `steps/import_.py` gained `dataset_summary(project)`,
  which rebuilds the same tables from the saved dataset. The app needs them *after* a
  subprocess import, when a return value is not available anyway. Shared helpers
  (`speaker_role_rows`, `narrator_groups`) keep it DRY.
- **Topics has no separate page**; the set picker and the topic-list upload live on the topics
  step page, so there is one page per step and no split-brain navigation.
- **`tests/app_main.py`** exists because NiceGUI's harness builds the app under test by running
  a "main file". It is three lines and calls `server.build()`, so it cannot drift.
- **`/api/quit` requires a custom header**, which a web page in the user's browser cannot send
  cross-origin — otherwise any site could stop a running corpus job.
- **pytest config added** (`asyncio_mode = "auto"`, `main_file`) and **`pytest-asyncio`** added
  to the `dev` extra. Users are unaffected.

### Still to do before this can ship

1. **The Mac checklist (§9)** — none of it has run on hardware. The launcher build, the TCC
   prompt for a grandchild process, sleep survival of a *subprocess*, and the real browser
   flows are all unverified. `tests/test_app_launcher.py` has a macOS-only test that builds a
   real bundle; run the suite on the Mac to exercise it.
2. **Docs (Phase E)** — `docs/APP.md`, the SETUP.md restructure, README, bundle regeneration.
   Left undone deliberately: SETUP.md is live for colleagues and its rewrite should follow the
   Mac test, not precede it.
3. **LICENSE** (decision 12) and **exact pins** (decision 5).
4. **Merge to main** — and only then resume version-bump-per-push.

## 15. The review round

Four reviewers went over the built code (process machinery, the non-technical user's journey,
safety of a local server holding transcripts, and the tests). They found six bugs that would
all have reached a user, and about a dozen smaller things. Everything below is fixed on the
branch, with a test for each.

**Bugs**

1. **The log printed itself twice.** `Job.since()` answered "nothing new" with the whole
   buffer, and a page redraws for things that add no output — a question arriving, a run
   ending — so the finish of every run duplicated its own history. Past ~2500 lines the
   duplicate also pushed the real beginning out of the pane.
2. **Dropping files did nothing.** Both upload handlers used a NiceGUI event API that does not
   exist in the pinned version; the uploader turned green and no file was written. This is the
   first thing anyone does. Tests now drive NiceGUI's own upload machinery, so a version bump
   cannot break it quietly again.
3. **Pages never refreshed after a run.** The review pages a demo had just written were never
   linked, because the page had been built before they existed — and the app suppresses the
   CLI's own auto-open. The demo-first loop broke exactly at "now read it".
4. **The dashboard misjudged locations.** It looked for a file `locations map` writes, not
   `locations tag`, so after a full locations run it still said "Next: run locations". Now
   read from the run each step records in state.json.
5. **Topics review links pointed at filenames no step writes** (and would have listed every
   set's pages at once). Each step now names its own review pages in `content.py`.
6. **Configured-but-not-discovered topic sets vanished** from the picker — `available_sets`
   was handed the root config instead of its `topics` section.

**Things that were true but shouldn't have been**

- **Stop did not stop.** Every step queues the whole corpus up front, and
  `with ThreadPoolExecutor(...)` drains the queue before letting Ctrl-C through — minutes of
  further paid calls after clicking Stop, then a SIGKILL. New `core/parallel.worker_pool`
  cancels what has not started. This fixes Ctrl-C in the terminal too, not just the app.
- **The launcher swallowed every startup failure.** A double-click just did nothing, with the
  reason in a log file. It now waits for the server to answer and shows the log's tail in a
  dialog if it never does. (Writing the test found a second bug: `mkdir` was inside the group
  being redirected, so the log could not be created.)
- **A spawn failure wedged the app** — a job stuck in "running" forever, no way out but killing
  the server from a terminal. The realistic trigger is a project folder renamed in Finder.
- **The local server answered to any hostname** (DNS rebinding: a page elsewhere could become
  same-origin and read the review pages, which are the transcripts) and **could be framed**
  (two clicks on an invisible frame = an approved corpus run). Both closed.
- **Quitting was unconditional**, so a launcher double-clicked out of habit after an update
  would kill a live run; and the version check was two-way, so an old copy could evict a newer
  server.
- **Declining at the cost prompt was reported as a failure.** It is now "cancelled".
- **A crash with no ToolkitError showed an empty red box.** Now the last lines and a copy
  button — this is the likeliest first failure (a bad API key surfaces this way).
- **`toolkit sample` was reachable only by failing first**, guaranteeing that a new user's
  first click ended in red. It is now step 0 on the clip and label pages when missing.
- **An unrecognised question hung invisibly** (`toolkit update` can ask one). Unfinished output
  that goes quiet is now shown with a text box to answer it.
- Uploads silently overwrote existing transcripts and topic lists; `.env` was written 0644;
  run times were shown in UTC as if local; "units" and "corpus" appeared in the interface;
  `map`/`rollup` were buried in a collapsed "other things" list although they are required
  steps; the export path ignored a renamed output file; the health endpoint published the
  workspace path for no reader.

**Test count: 256 before the app, 361 now.** The additions worth knowing about: the confirmation
prompt is driven through a real pty against the real `choose_transport`; a run is proven to
survive leaving the page and coming back; uploads go through NiceGUI's own event path; the
host and framing rules are checked against a real server on a real socket.

Still not verified by anything: the Mac checklist in §9. That is the remaining work.

## 16. Next session (agreed 2026-07-29, before compaction)

Three things, in this order.

### 1. LICENSE → MIT — DONE (6ff28b3)

Standard MIT text, copyright holder **Marlon Kegel** (the holder already named in the old
notice; change it if INCITE/Columbia should hold it instead). Declared in `pyproject.toml` as
an SPDX expression — `license = "MIT"`, `license-files = ["LICENSE"]`, build floor raised to
`setuptools>=77` — and verified in a built wheel: `License-Expression: MIT`, LICENSE shipped
under `dist-info/licenses/`. README gained a License section; nothing else in the repo assumed
the old wording. The docs bundle was regenerated (the README is part of it) — `test_docs.py`
catches that if it is forgotten.

### 2. A real app icon, generated with gpt-image-2 — BLOCKED ON BILLING

The current icon is a placeholder I drew with matplotlib. Replacing it with something that
combines **INCITE's logo** and **the idea of a toolkit**. Marlon's brief: *simple and minimal —
a simple toolkit icon with the company logo on it somewhere.* He wants **10 genuinely
different options**, then he picks and we refine.

- **Company logo: `/home/mkegel/projects/incite/brand/incite-logo.png`** (uploaded by scp
  2026-07-29; 396×396 RGBA). It is a square signet: field `#2A3E55` (dark navy), a capital
  letter **"I"** — for Incite — in `#E7DFCC` (cream): a plain upright bar with a 45°-cut flag
  at the top left, no crossbars, no serifs. Deliberately kept OUT of the public repo; only the
  finished app icon goes in.
**Everything is written and waiting on one thing: every billable OpenAI call from this machine
is refused.** Diagnosed 2026-07-29, and it is not the icon code:

| probe | old `OPENAI_API_KEY` | new `ICON_API_KEY` |
|---|---|---|
| `models.list()` (free) | **OK, 143 models** | — (key has no list permission) |
| `responses.create` gpt-5.4-mini | 429 `insufficient_quota` | 429 `insufficient_quota` |
| `images.generate` gpt-image-2 | 400 `billing_hard_limit_reached` | 400 `billing_hard_limit_reached` |
| `images.generate` gpt-image-1 | 400 `billing_hard_limit_reached` | 400 `billing_hard_limit_reached` |

Auth is valid (the free endpoint works), so it is not the key, the key's permissions, the
endpoint, or the model — **plain text generation is refused too**. The org's July spend was
$57.94 of a $5,000 budget, so the block is below the org budget: most likely a **per-project
budget** on the project both `sk-proj-` keys belong to (platform.openai.com → Settings → your
project → Limits), or an empty prepaid credit balance (Settings → Organization → Billing),
which is what `insufficient_quota` classically means. Clear that, then run the three commands
below; nothing else needs deciding.

**Note the mark is a capital letter "I"** (for Incite), not the numeral 1 — the prompts say so
explicitly, since a model told "1" draws a different glyph.

```sh
cd ~/projects/incite/brand
/opt/venvs/incite/transcript-toolkit-dev/bin/python make_icon_options.py     # ~10 images
/opt/venvs/incite/transcript-toolkit-dev/bin/python make_contact_sheet.py    # then look
/opt/venvs/incite/transcript-toolkit-dev/bin/python install_icon.py 4        # once picked
```

What was settled while writing it:

- **API shape**: `client.images.edit(model="gpt-image-2", image=[logo], prompt=..., …)` — the
  edits endpoint takes reference images, so the signet goes in as a picture rather than a
  description. `input_fidelity` is rejected by this model (it always reads inputs at high
  fidelity) and `background="transparent"` is not supported either, so the options come back as
  full-bleed squares.
- **The Dock shape is applied locally**, not asked for in the prompt: macOS (unlike iOS) does
  not round an app icon for you, so `iconlib.dock_shape` masks each option into Apple's rounded
  square with a transparent margin — matching what the matplotlib placeholder did. That is what
  the contact sheet shows and what `install_icon.py` writes.
- **The ten ideas differ in subject, not styling** — a shared house-style block fixes the two
  colours, the flat vector treatment and "no text except the numeral", and only the subject
  line changes: closed toolbox with the signet as its front plate · open toolbox with tools
  standing in it · the numeral *as* a screwdriver · a wrench turning the signet as a bolt · a
  transcript page with a tool across it and the signet stamped on it · a speech waveform where
  one bar is the numeral · tools fanned from the signet as a pivot · the numeral cut out of a
  toolbox as negative space · numeral-and-hammer as one monogram · a speech bubble that is also
  a toolbox.
- **Where the scripts live**: `~/projects/incite/brand/`, outside the public repo, because they
  depend on the signet. See `brand/README.md`. `make_icon_options.py` skips options whose PNG
  already exists, so a re-run only fills gaps; passing numbers regenerates just those.
- Winner becomes `src/transcript_toolkit/defaults/app/icon.png` (1024×1024) via
  `install_icon.py`. Delete `scripts/make_app_icon.py` then — its docstring is the provenance
  of the placeholder only, and `brand/README.md` takes over that job.

### 3. Marlon tries the app on his MacBook

The branch is not merged, so he installs from it by name. Exact commands:

```sh
uv tool install --force git+https://github.com/MarlonKegel/transcript-toolkit.git@app
toolkit app --install-launcher
```

Then open **Transcript Toolkit** from Applications (drag it to the Dock). It may ask once for
access to Documents — expected, say yes.

To go back to the released version at any time:

```sh
uv tool install --force git+https://github.com/MarlonKegel/transcript-toolkit.git
```

He will have feedback from real use; expect a round of changes. The §9 Mac checklist has still
never run on hardware — this is that.

### Then, and only then

Docs pass (SETUP.md restructure per §10 Phase E, README, regenerate the bundle), exact-pin the
dependencies, merge `app` → `main`, resume version-bump-per-push, delete
`scripts/mac_launcher_smoke_test.sh` and this file.

## 17. Feedback round 1 (2026-07-29, from Marlon using the app on his MacBook)

Fourteen items, all done in `eed57e8`. Marlon's standing instruction with any feedback: **decide
each time whether it is a UI fix or belongs at the CLI level too — the two must never drift.**
That column is the point of this table.

| # | What he found | What changed | CLI? |
|---|---|---|---|
| 1 | No way to browse for a project folder | `pages/browse.py` — a server-side folder picker (a browser cannot hand a page a path; the server is the Mac, so the listing comes from there). Typing a path still works. | UI only — the terminal has tab completion |
| 2 | "Does the example path have *my* username on other machines?" | It already did (`Path.home()`). Pinned by a test that fakes a different home. | no change |
| 3 | Dropped 8 transcripts, saw 2 | `on_multi_upload` — one event for the whole drop, list redrawn once. Before: 8 concurrent handlers each rebuilding the section holding the upload box. | UI only |
| 4 | "replacing a transcript silently would be worse" reads as a comment on the user | Rewritten to say what happened and what to do. **`tests/test_user_facing_wording.py` now walks every string literal in `src/` (docstrings excluded — comments are not in the AST) for wording that justifies a design decision.** | repo-wide guard |
| 5 | The import card did not list the transcripts | `workspaces.transcript_rows()` → every `.docx` with the id import gives it and whether it is in the dataset, colour-coded. "Drop .docx files here" kept. | `toolkit status` already flags `import_stale`; not duplicating a 43-row list there |
| 6 | Terminal needed explaining, and folding away | Folded `ui.expansion` with an `i` explaining that the app is a window onto a CLI; one line above it always shows the last output. | UI only |
| 7 | Terminal still showed the previous project's run | `AppContext.open()` clears the job; refuses to switch while one is live (it holds that project's terminal). | UI only (one workspace per CLI invocation) |
| 8 | "My Oral History Project" appeared without being entered | **One name is typed, the other follows.** `project.folder_name` / `display_name`; `init_project(dest, name=)`; `toolkit init --name "..."` derives the folder, `toolkit init <dir>` derives the name. The app asks for the name and shows the folder before creating it. | **yes — same rule both sides** |
| 9 | "Open project" showed the folder name | Shows `project_name()`; the path is on the line below, where a path belongs. | UI only |
| 10 | Import with nothing new looked like it did nothing | Dialog saying so, with "Import again anyway" (a re-import is still how you pick up an edited transcript). | UI affordance only — `toolkit import` stays unconditional so scripts keep working |
| 11 | Demo sample belonged on the workspace page, and should be choosable | `pages/sample.py`, used by the workspace page and borrowed by step pages when unchosen. Random or hand-picked, 1–10, cost note above 5. | **yes — `--interviews` with `--n` now fills the remainder at random** |
| 12 | Chunk preview was jargon, and terminal-only | Under **Advanced** with an `i`; renders as a table in the app. `chunk_preview()` / `batch_preview()` return the data and the print functions render it, so terminal and app cannot disagree. | print output byte-identical |
| 13 | "Re-render review pages" failed in the terminal, silently in the UI | `Action.needs`; `content.missing_for()`; the button is disabled with a tooltip naming what is missing. | CLI keeps erroring with its message — right for a terminal |
| 14 | Topic lists should be editable in the app | `app/topic_lists.py` + `pages/topics_editor.py`. Edits the same spreadsheet the run reads; validated by `read_topic_rows`, **extracted from `load_topic_set` so the editor's errors are literally the run's**. Autosave every 20 s; first save names the set; before that it lives in `example_topics.csv`, which set discovery excludes. | shared validation |

Tests 363 → 487. Nothing here changed a prompt, a taxonomy text or a cache key.

**One thing worth knowing for the next round:** the eight-file regression test passes against the
old code too — NiceGUI's test harness dispatches `handle_uploads` without the client teardown
that made the live version drop files. It pins the behaviour, it does not reproduce the bug.

Still to come: Marlon's second round, and the icon (§16 item 2) once the OpenAI project budget
is raised.

### Round 1, item 15 (found while installing, same day)

`--install-launcher` said "Created /Users/marlonkegel/Applications/Transcript Toolkit.app" and
then "Open your Applications folder" — but **Finder's sidebar "Applications" is `/Applications`**,
and `~/Applications` is a different folder that appears nowhere in it. Marlon looked in the
sidebar one first, as anyone would.

Now: `/Applications` when writable (it is, for admin users, without sudo — group `admin`,
mode 775), falling back to `~/Applications` on a managed Mac. `where_to_find()` gives the
folder-specific instructions, used by both the CLI and the Settings page, and an older copy of
ours in the other folder is removed so two same-named apps can't coexist. A same-named bundle
that is *not* ours (no matching `CFBundleIdentifier`) is left alone.

Reinstalling moves the bundle, so macOS may ask once more for Documents access — expected, and
already documented in APP.md.

## 18. Feedback round 2 (2026-07-29, still the same afternoon)

First, a process failure worth remembering: Marlon reported the naming change not working, and
the reason was that **nothing had been reinstalled** — the app he was looking at predated the
fix. The version had sat at 0.1.8 across every push, so two builds were indistinguishable from
inside the app. Now: **bump `__version__` on every push to this branch**, and the version is
shown in the app header. Reinstalling is also not enough on its own — the running server keeps
serving the old code until it is quit and reopened.

| What he found | What changed |
|---|---|
| Deleted the open project folder in Finder → every page said "config can't be found", **Settings returned a 500 with a raw `FileNotFoundError`** | `AppContext.check_still_there()` runs at the top of `shell()`, closes the project and records where it was; every page is then in the "no workspace open" state it already handles. `settings.py` guarded its `read_text()` — that unguarded call was the 500. |
| "Can't find the config file" describes a symptom, not the problem | `load_root_config` says the folder is not there; `find_project` distinguishes *no folder at that path* from *a folder that is not a project*, and tells you to open the project folder itself rather than the one it sits in (the commonest miss with a folder picker) |
| Wanted to be asked what happened, with "I moved or renamed it" / "I deleted it" | Exactly that, on the workspace page. Moved → the folder picker, starting in the old parent; deleted → forget it and start clean |
| Wanted to delete a project from the app | Settings → Delete this project. Counts what goes with it, requires typing DELETE, refuses while a run is live and refuses any folder without `.toolkit/project.json`. **On macOS it moves the folder to the Trash** (osascript → Finder), so a wrong answer is recoverable |
| Settings should be a left sidebar behind a gear, not another tab | `ui.left_drawer` built by `shell()` on every page, gear in the header's top left. `settings_body()` is the single implementation; `/settings` still resolves and opens the drawer. **The version check moved to drawer-open**: it calls GitHub, and the drawer is now built on every page — leaving it on page load would have put a network round trip behind every click |

Tests 498 → 514. The two that matter most: every page is opened with the project folder deleted
underneath it, and the recovery card's two buttons are clicked.

### The OpenAI block — RESOLVED 2026-07-29

The org's **credit balance was −$57.94**. Auto-recharge was switched on (top up to $100 below $5)
but had never once succeeded: the card is fine when charged from a browser and declined for the
unattended charge, and a failed auto-charge leaves no invoice, so Billing history showed nothing
at all. Marlon bought $100 by hand and everything unblocked immediately. Neither spend limit was
ever involved — project, org, and a limit a colleague raised mid-diagnosis all turned out to be
irrelevant. Full trail, including the dead ends, in the memory note `openai-billing-block.md`.

Two things came out of it:

- **The ten icon options exist** (`~/projects/incite/brand/icon-options/`, ~$0.40), awaiting
  Marlon's pick.
- **A real bug, fixed in v0.2.2** (`52c4fe2`). `insufficient_quota` arrives as HTTP **429**, so
  `RateLimitError` being in `_retry`'s transient list meant an unfunded account burned the whole
  backoff ladder — ~250s per call, on every parallel worker — and then died in a traceback.
  `core/llm.py` now recognises billing refusals, raises at once, and explains them: the credit
  balance *before* the spending limits, nothing is lost, and the auto-recharge trap named
  explicitly. `core/batch.py` wraps submission the same way. Needed no app change at all — the
  app runs the real CLI on a pty and never calls the API itself, so `core/` is the single place.

## 19. Feedback round 3 (2026-07-29, evening) — VERBATIM, not yet triaged

Marlon asked for this to be stored word for word and left alone until the icon question is
settled. **Do not act on it before re-reading it in full.** No item below has been analysed,
scoped, or split into UI-vs-CLI yet — that triage is the first task of the next session, and the
standing instruction applies to every item: decide whether it is UI-only or belongs at the CLI
level too, because the two must not drift.

```
At the very top it says "Transcript Toolkit 0.2.1" and there is the preliminary icon left of it right now. It's too crowded with the settings also being on the left there. Instead, I now want the settings at the top right, the current project name at the top in the center, and the "Transcript Toolkit" + version can stay on the left. Of course, the preliminary icon should be replaced with the final icon once we've settled on one. Also, when you click on that, you should be brought back to a landing page. I basically want to merge the current Home and Workspace pages into one Workspace page and get a real Home page where you can see all the projects you have and at what stage they are, and where you can create a new project etc. The latter should be the page you get when you launch the app and when you click on the app icon at the top left.

Also, on the current workspace page it currently lists all the interviews twice, once under 'Transcripts' and then again under 'What was imported'. This is unnecessary and gets out of hand really quickly on large projects. Instead, this should be deduplicated and there should be one table/list that combines the information of those two lists/sections. Also, this list should show at most 10-15 interviews at a time (depending on how much vertical space each row takes) and then should be scrollable inside (a bit like the current Transcript section already is but the 'What was imported' section isn't). This is to prevent burying the subsequent (and very crucial) 'Demo Interviews' section (which should be renamed to 'Pick sample of interviews for Demo' or something like that). Especially given that I want us to merge the current home page and workspace pages into one workspace page , we need to be careful that it stays clear, well-arranged and non-cluttered.

As for the demo section, I want the 'how many' field to sit above the "Draw them at random vs 
Choose the interviews myself" selection to make clear that you don't have to pick all of them. we shouldn't allow people to have less than 3 demo interviews. Also, once you've run the demo selector, there should be a list of the interviews that were picked for demo; currently it's only a very small line after "Demos run on 5 interviews:" and then there is also a section after it that says "Choose demo interviews — finished
1s" and then it only shows one of the 5, in my case:
ursu_viorel_20250416_session1 . This is confusing.
Also, users should be able to edit the demo sample list (remove individual interviews, add specific ones, or add x more random interviews; all making sure it stays between 3 and 10).

It should also be more clear when a step is running. I.e. it should be somehow shown with a progress bar or at least a x out of y steps done indicator that is not just at the very bottom with the terminal viewer. Also, the terminal viewer should be its own section at the very bottom and it should have the actual heading "Terminal Viewer". Currently, there is no such heading there is only something that says "Terminal" and can be extended. Also, it's weirdly combined with the status indicator, e.g. reading "Clip — demo — finished
56s
Review them; adjust config.yaml / prompts/ and re-demo if needed. Then run `toolkit clip` for the full corpus." for me on the clipping page right now, but that's after I've clicked the "Run the Demo" step all the way at the top and there is the "Review pages" section, the "Other things this step can do" options, and the "Advanced" options all between that button and the status indicator so it's not clear that it's showing the status for that specific command. Also, I don't really like the "Other things this step can do" expandable option. This should somehow be integrated into the rest of the page where it's things that are going to be used with some frequency, or if it's very niche like the preview chunking step it should go to the bottom, maybe just before the terminal viewer, into an "Advanced/Optional steps" section (there must be a better name for that, I'm open to suggestions). 

Also, I actually don't like that the "Run the Demo" and "Run it on everything" buttons are both visible from the start since you shouldn't be able to run it on everything before you've run the demo. We should keep the explanation, but it should just show "Try it" with the "Run the Demo" button initially, and then once you've run the demo it should give you the review the demo button in big (nudging you to actually do that) and then give you the option to edit the prompt or the settings for this step and rerun the demo OR to run it on the whole population. 

This makes me realize that there does not seem to be any way to view or edit the prompts for each step in the app right now. This, of course, needs to be addressed. 

Also, I actually don't like the setting page as it is right now, i.e. as a yaml editor. I think we can just incorporate the comments as explanation in the UI (in some standard way so that editing the comments automatically adjusts the explanation for the corresponding setting/parameter) and then make the options actual settings toggles. 

Then, all settings that pertain to the project and toolkit/app as a whole should sit in the expandable sidebar (upon clicking the wheel), whereas all settings that pertain to a specific step should actually sit on the page for that specific step. 

I don't mind that the 'Open the review pages' button opens a new tab, but that tab should be just slightly more navigable, i.e. it's good that it throws you on a page where you see all the interviews listed but then when you click on one of them you should get a little arrow to the left icon in the top left corner to return to the page that lists all the interviews for review. You shouldn't have to use the browsers own back button (although you of course still can). 

That's enough feedback for this round. Save it and then we'll treat the icon first.
```

This round is larger than 1 and 2 combined and is mostly **structural** — a new Home page, Home
and Workspace merged, the step page resequenced around demo-then-full, prompts editable in the
app, and `config.yaml` replaced by real controls split between the sidebar (project/app-wide) and
each step's own page (step-specific). Expect it to need its own plan rather than a fix list.

## 20. Feedback round 3 — triage and what was built (2026-07-29, evening)

§19 is Marlon's own words. This is the item-by-item answer, with the standing UI-vs-CLI call in
the last column. Alongside it he asked for the app's colours to be the icon's colours.

It was planned as one change rather than a list, because several items decide each other: where
step settings live depends on the step page's new shape, and the Home page needs a per-project
"stage" that nothing computed before.

| # | What he asked for | What changed | CLI? |
|---|---|---|---|
| 1 | Header: gear top **right**, project name centred, wordmark + version left, the real icon, clicking it goes Home | `pages/common.shell` — three flex zones; `ui.image("/app-icon.png")`, served from the package by `server.py` so the header and the Dock icon can never be different pictures. The drawer became a `right_drawer`. | **yes** — two CLI messages said "the gear in the top left corner"; both now say right |
| 2 | Merge Home + Workspace; a real Home listing every project and its stage, with project creation | `pages/home.py` is now the project list (name, folder, transcripts, "3 of 5 steps run on everything", the next thing to do, Open) plus open-by-path and create. `pages/workspace.py` is one project: next action, the pipeline, key, transcripts, demo sample, folder. New `app/stage.py` holds `ran_fully` / `step_state` / `next_action` / `summary`, which both pages read. | UI only, **but** `server._resolve_workspace` now remembers whatever it opens, so a project given with `--project` or walked up to appears on Home |
| 3 | The transcript list appeared twice; one combined, scrolling table, 10–15 rows | `pages/transcripts.py` — one row per transcript: imported state, filename, narrator (+ session count), paragraphs, a timestamp warning where the transcript is turn-timed only. Scrolls inside itself at `theme.LIST_HEIGHT`. The aggregate speaker-role table (the check that catches a misconfigured interviewer label) is folded under it as *Who the speakers are*. | **shared data**: `steps/import_.interview_rows()` — a dataset question, so it lives with the step, not in `app/` |
| 4 | Demo section renamed; "how many" above the random/pick choice; never fewer than 3; list what was picked; make the list editable (remove / add one / add x random, 3–10) | `pages/sample.py` — *Pick the sample of interviews for demos*; size first with the bounds spelled out; the picked interviews listed one per line, each with an ×; "add this many at random"; "or add a particular interview". Every edit runs `toolkit sample` with the interviews it should end up with, so the app never writes the sample file itself. | **yes** — `core/sampling.MIN_N`/`MAX_N` (3/10), enforced by `cli.cmd_sample` and read by the app, so typing the command meets the same rule |
| 5 | Show progress while a step runs, not buried at the bottom | Every step already prints `  [3/12] …` per unit; `content.progress_of()` reads that back and `common._progress` draws it as a bar with "7 of 12 clips". The Batch API's own `[  42s] status=…` line deliberately does not match. | no change — the app reads the count the CLI already prints |
| 6 | Terminal viewer its own bottom section headed "Terminal Viewer", separate from the status, which should sit by the button that started it | `run_panel` split into `run_status` (state, progress, the CLI's question, errors, Stop) and `terminal_viewer` (heading, command, output, always visible). Every page places `run_status` immediately below the buttons that start something, and the viewer last. `inline_state(title)` answers a click on a Run button further down a page. **A successful run no longer echoes the CLI's last line** — that is where "Then run `toolkit clip` for the full corpus" was coming from. | UI only |
| 7 | Dislikes "Other things this step can do"; frequent things on the page, niche ones in a bottom section | `Step.followups` → `Step.extras`, drawn at the foot of the page as **Extra tools** ("nothing here is needed for a normal run"). The `advanced` flag is gone. The threshold aid was not niche — it is the decision made *while* rolling up — so `Action.aids` puts it beside the rollup button. | UI only |
| 8 | Don't show "Run it on everything" from the start: Try it → a big review button → then adjust-and-redemo **or** run everything | The step page is `1 · Try it` → `1 · The demo has run` / `2 · Read what came out` (review buttons + what to look for, per step) → `3 · Then one of these` (*Not right yet?* / *Happy with it?*). Only one demo button exists at a time. | UI only — the toolkit already refuses a full run without a current demo; the app now stops offering what would be refused |
| 9 | No way to view or edit the prompts | `pages/prompts.py` — the step's own prompt file, editable, with *Put the original back*. New `core/prompts.py` answers "which file does this step read?" (a topic list may bring its own), so the app names no prompt files. | **yes** — `toolkit status` now prints each step's prompt file and how to restore one |
| 10 | The settings page should not be a YAML editor: use the comments as explanations, real controls | `core/settings.py` — a schema of the blessed settings, `explanations()` reading each key's comment out of config.yaml, and `set_value()`/`save()` editing the file in place. Write → re-read → verify only the named keys changed, else refuse and keep the user's file. `pages/settings_form.py` renders toggles, selects, chip lists, number lists, key→value rows and the rollup composite. The scaffold's config.yaml gained a comment for every blessed key. | **yes in effect** — the app writes exactly what a person would type, comments and all; `docs/CONFIG.md` documents the two conventions this relies on |
| 11 | Project/app-wide settings in the sidebar, step-specific on the step's page | Drawer: project name, version, desktop app, files, delete, quit. Step pages: model, thinking effort, and each step's own keys (topics also gets its topic list's rollup rule). Import has no page of its own, so its settings are on the workspace page beside Import; export's are on the export page. | UI only |
| 12 | The review tab needs a back arrow to the interview list | `core/reviewdoc.document(back=…)` → `← All interviews` above the title on every per-interview page (clip, label, topics — topics points at its own set's index). | **yes** — the pages are the toolkit's own artifacts, so a terminal user gets it too |
| 13 | The app's colours should be the icon's colours | `app/theme.py` — navy `#2A3E55` and cream `#E7DFCC`, light and dark, with `tk-note` / `tk-warn` / `tk-fail` panels replacing the Tailwind blue/amber/red. `core/reviewdoc` CSS retuned to match. | **yes** for the review pages |

**One deliberate reading of item 11.** The OpenAI key stayed on the workspace page rather than
going into the sidebar with the project-wide settings. It is a credential and the first thing a
new project needs, not a tunable; it collapses to one line once set, so it does not clutter.

Tests 524 → 590 (+1 skipped). New: `test_settings.py` (the config writer, every setting kind, and
that a hand-reindented file is left alone), `test_review_pages.py`, `test_app_progress_and_prompts.py`.
`tests/test_app_pages.py` now runs its server with its own HOME, so it stops writing test paths
into the developer's list of projects.

Nothing here changed a prompt text, a taxonomy text or a cache key.

## 21. Feedback round 4 (2026-07-30) — triage and what was built

Nine items, four of them arriving mid-round. Same standing rule in the last column.

| # | What he asked for | What changed | CLI? |
|---|---|---|---|
| 1 | The review tab still had no way back to the interview list | Nothing to build — v0.2.4 added it (`reviewdoc.document(back=…)`). His pages were **written before that**, so they do not have it. Review pages are generated artifacts and go stale when the toolkit improves, so the fix is discoverability: **Rebuild these pages** now sits beside the review links on every step page (it was buried in Extra tools), free and instant. | already CLI (`toolkit <step> annotate`) |
| 2 | A project cost report: everything ever billed, per step and total, updated whenever anything runs | `toolkit cost` was already the actual-spend report, but it deduped to the latest record per cache key — i.e. *what the current results cost*, not *what was spent*. Now every record counts, because a step only appends one when it actually calls the API. New `spend_report()` returns it as data; `run_cost` prints from it and `pages/spend.py` draws from it, so the two cannot disagree. On the workspace page in full, and one line per step page beside the buttons that spend. | **yes — the semantics changed for both** |
| 3 | Keep the sync/Batch choice at the confirmation, with an explainer | Already there for every batch-capable step (`console.choose_transport`'s three-way menu, shown as three buttons). Added the `i` beside them (`content.TRANSPORT_EXPLAINER`), and fixed the block above them: it was rendered `whitespace-pre-line`, which **collapses the spaces the CLI lines the two prices up with**. Clipping cannot batch, so it still asks a plain yes/no. | no change |
| 4 | The status line runs off the right-hand edge | It was `truncate`d, so a long interview id vanished rather than wrapping. Everything in the status panel now wraps (`pre-wrap`/`break-words`), including the error tail and the question block. | UI only |
| 5 | House rules: writable in the app, and the justify addendums should not be selectable | **A real bug first**: the picker offered `prompt_addendums/x.md` while `steps/label` resolves the path from the project root, so anything chosen there failed at run time. `core/prompts.addendums()` now returns workspace-relative paths, and `write_addendum()` makes one from the app. The toolkit's own justify files are excluded by looking up every step's `justify_prompt` — not by name. Justify itself was already right: on for demos, off for full runs, `--justify` a CLI flag only. | **yes** — the path bug was in the picker; a test now pins the two ends together |
| 6 | The prompt box is too short, and should look like a field | The height was set on the wrapper, not the textarea, which is where the gap came from — now `input-style="height: 36rem"`. Every outlined field in the app is white (`theme`), so anything you can type into reads as paper. | UI only |
| 7 | More than one topic list, kept apart, with their own prompts and settings; tabs | Multiple lists already worked end to end (separate `--set`, cache, state key, deliverables). What was missing: a tab per list with its own state, an **Add a topic list** tab that works when lists already exist (before, the editor only appeared when there were none), a per-list prompt (*Give this list its own prompt* splits it off the shared one), and per-list model/reasoning. | **yes** — `sets.<set>.{model, reasoning}` merged in `topics/tag._context`; the fingerprint already covers both, so one list's change stales only that list |
| 8 | An uploaded topic list should be editable in the same editor | It refused anything that was not `.csv`. It now edits the file that is actually there, `.xlsx` included — rewriting only the sheet the toolkit reads and leaving any other sheet in the workbook alone. | shared editor/validation |
| 9 | The topics demo page needs line breaks in the clip text | `<pre>` had `overflow-x:auto`, so a paragraph was one long scrolling line. Now wraps. | **yes** — the review pages are the toolkit's own artifacts |

Tests 592 → 609.

**Worth knowing for the next round.** NiceGUI HTML-escapes `$` in the served page (`&#36;`), so a
page test asserting a money figure has to expect that, not `$8.00`.

## 22. Merging `app` into `main` — handover (2026-07-30)

Marlon has judged the app good enough to ship and is presenting it shortly. This section is
written for whoever does the merge, and is the one place that has to be read first.

### Where things stand

| | |
|---|---|
| Repo | `~/projects/incite/transcript-toolkit` → public `MarlonKegel/transcript-toolkit` |
| Branch | `app` at **`d940aac`**, version **0.2.5**, working tree clean |
| `main` | at `c0e7d29`, **strictly behind** — 25 commits, 92 files, +10664/−249, nothing on `main` that `app` lacks, so the merge can fast-forward |
| Tests | **609 passed, 1 skipped**; CI green on `d940aac` |
| Interpreter | there is no `python` on PATH — use `/opt/venvs/incite/transcript-toolkit-dev/bin/python` |

**`main` is what colleagues install from, so pushing there ships instantly.** That is the whole
risk of this merge; the code itself has been exercised.

### The one thing that actually blocks it

**`README.md` and `docs/SETUP.md` never mention the app.** `docs/APP.md` exists and is complete,
and it is in the docs bundle (`scripts/build_docs_bundle.py`, `DOCS` list) so `llms-full.txt`
covers it — but nothing at the front door links to it, and the README's Quickstart is
terminal-only. Merging as-is ships the app undiscoverable to exactly the people it was built for.

Minimum before the merge:

1. **README** — add `docs/APP.md` to the Documentation index, and put a point-and-click opening
   in the Quickstart *above* the terminal one (`uv tool install …` then
   `toolkit app --install-launcher`). Most colleagues will never type a command.
2. **docs/SETUP.md** — after the install steps, a short "if you would rather not use Terminal"
   pointing at APP.md. It currently ends by sending everyone to WORKFLOW.md.
3. **docs/WORKFLOW.md** — one line that the same demo-first loop is what the app's step pages do.
4. Regenerate the bundle: `.../python scripts/build_docs_bundle.py`. **`tests/test_docs.py` fails
   if the bundle is stale after any docs edit** — that is the guard, use it.

### The merge itself

```sh
cd ~/projects/incite/transcript-toolkit
git checkout app && git pull                       # confirm d940aac or later
# ... the docs edits above, committed on `app` ...
/opt/venvs/incite/transcript-toolkit-dev/bin/python scripts/build_docs_bundle.py
/opt/venvs/incite/transcript-toolkit-dev/bin/python -m pytest -q      # expect 609 passed, 1 skipped
git checkout main
git merge --no-ff app -m "the app: point-and-click over the same CLI (v0.3.0)"
git push origin main
```

`--no-ff` rather than the fast-forward it would otherwise be: one commit on `main` marking when
the app shipped is worth more than a tidy line. **Bump `__version__` to 0.3.0** on `app` before
merging — this is a feature release, and the version is shown in the app header, which is how
anyone tells which build they are looking at.

Watch CI on `main` afterwards, then have Marlon reinstall **without** `@app`:

```sh
uv tool install --force git+https://github.com/MarlonKegel/transcript-toolkit.git
toolkit app --install-launcher      # then quit and reopen the app
```

### Decisions to make, with recommendations

- **`APP_PLAN.md`** — §16 said delete it on merge. **Recommend keeping it.** §17–§21 are the only
  record of four rounds of feedback and the UI-vs-CLI call made for every item; nothing but
  itself links to it and it is not in the docs bundle, so it costs nothing to keep. If it must
  leave the repo root, move it rather than delete it.
- **`scripts/mac_launcher_smoke_test.sh`** — also slated for deletion, but
  `app/launcher.py` and `tests/test_app_launcher.py` both cite it as where the recipe was
  verified on real hardware. **Recommend keeping it**, or deleting it *and* rewording those two
  references in the same commit.
- **Exact-pin dependencies** — on the old list, and the one change that could break a fresh
  `uv tool install` on somebody else's Mac. It has nothing to do with the app. **Do it after the
  meeting, on its own.**
- **Version bump per push** — the rule for `app` was to bump every time. On `main` decide the
  cadence deliberately; the update check and `toolkit update` both read it.

### Do not "fix" these — each is deliberate and tested

- The **full-run button does not exist until a demo has been run**: the toolkit refuses that run
  anyway, so a button for it would only be a button that fails.
- **`toolkit cost` counts every call ever billed**, not the deduped current set. It is a report of
  money spent, and a step only appends a cache record when it really calls the API.
- The **demo-sample bounds (3–10)** live in `cli.cmd_sample`, not in `draw_interview_sample` —
  validation at the boundary where user input arrives; library callers and tests are unbounded.
- **`core/settings.py` edits config.yaml as text**, re-reads it, and refuses to write unless
  exactly the named keys changed. A file somebody has reindented by hand is left alone on purpose.
- The **OpenAI key is on the Workspace page**, not in the settings drawer: it is a credential and
  the first thing a new project needs, not a tunable.
- **Two path conventions**: a prompt name is relative to `prompts/`; `label.addendum` is relative
  to the workspace. `core/prompts.py` documents both. Conflating them was a real shipped bug.
- **NiceGUI HTML-escapes `$` as `&#36;`** in the served page — a test asserting a money figure has
  to expect that.

### Known, and fine

Marlon's own test project has review pages written before the back-link existed. Review pages are
generated artifacts: **Rebuild these pages**, beside the review links on each step page, brings an
old one up to date for nothing.
