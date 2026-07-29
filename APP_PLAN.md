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
| 6 | Icon | placeholder from `scripts/make_app_icon.py`. **Being replaced** — see §16 |
| 7 | Update UX | Update button + "Quit, then reopen"; a **Quit** button now exists (Settings) |
| 8 | Launcher install | explicit `toolkit app --install-launcher`, also a button in Settings |
| 10 | Job history | none persisted; state.json already carries last-run info |
| 11 | `TOOLKIT_YES` | left undocumented; the app never uses it |
| 12 | LICENSE | **MIT** (decided 2026-07-29) — not yet written |
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

### 1. LICENSE → MIT

Decision made. Replace the proprietary "internal use" notice with the standard MIT text
(copyright holder: check with Marlon — his name, or INCITE/Columbia). Grep README, pyproject
and docs for wording that assumed the old licence.

### 2. A real app icon, generated with gpt-image-2

The current icon is a placeholder I drew with matplotlib. Replacing it with something that
combines **INCITE's logo** and **the idea of a toolkit**. Marlon's brief: *simple and minimal —
a simple toolkit icon with the company logo on it somewhere.* He wants **10 genuinely
different options**, then he picks and we refine.

- **Company logo: `/home/mkegel/projects/incite/brand/incite-logo.png`** (uploaded by scp
  2026-07-29; 396×396 RGBA). It is a square signet: field `#2A3E55` (dark navy), numeral "1"
  in `#E7DFCC` (cream) — a plain stem with a diagonal flag at the top left, no base serif.
  Deliberately kept OUT of the public repo; only the finished app icon goes in.
- **Read first**: https://developers.openai.com/api/docs/guides/image-generation — model
  `gpt-image-2`. Check whether to use generation or the edits/reference-image endpoint so the
  logo can be passed in rather than described.
- **Key** — the API is billed to Marlon's key. Look for it in a workspace `.env`
  (e.g. the PNL-test workspace) or ask; do not print it.
- Ten options must differ in *idea*, not in styling: e.g. logo-on-a-toolbox, the "1" as a tool
  handle, tools arranged in the signet's square, a wrench forming the numeral, etc. Save them
  numbered under `/home/mkegel/projects/incite/brand/icon-options/` so Marlon can view them.
- Winner becomes `src/transcript_toolkit/defaults/app/icon.png` (1024×1024). Delete or
  repurpose `scripts/make_app_icon.py` once a real icon replaces the drawn one.

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
