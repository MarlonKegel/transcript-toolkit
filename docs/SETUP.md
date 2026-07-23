# Setup (Mac)

One-time setup takes about 15 minutes. You'll copy commands into **Terminal** (find it with
Spotlight: press `⌘ Space`, type "Terminal", press Enter). Paste each command with `⌘V` and
press Enter, then wait for it to finish (you get the prompt back).

## 1. Install uv (a Python installer/manager)

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Close the Terminal window and open a new one afterwards (so the `uv` command is found).

## 2. Install the toolkit

```sh
uv tool install git+https://github.com/MarlonKegel/transcript-toolkit.git
```

Check it worked:

```sh
toolkit --version
```

To update to the latest version later:

```sh
uv tool upgrade transcript-toolkit
```

## 3. Create a project workspace

Pick a folder name for your project (here `my-archive`):

```sh
cd ~/Documents
toolkit init my-archive
cd my-archive
```

This creates the project folder with everything in place: `config.yaml` (your settings),
`prompts/` (editable prompt texts), `topics/` (your topic lists go here), `data/` (transcripts
go here), `outputs/` (results appear here), `diags/` (review files appear here).

## 4. Add your OpenAI API key

Every LLM step calls the OpenAI API with a key billed to your team. Ask your admin for a key.
`toolkit init` already created a `.env` file inside your project folder — you just need to add
the key to it. Make sure you are inside the workspace (the `cd my-archive` from step 3), then
open it (it's hidden in Finder — in Terminal: `open -e .env`) and paste the key after the `=`:

```
OPENAI_API_KEY=sk-...
```

## 5. Add transcripts and import

Copy your SYNC'd transcript `.docx` files into `data/` (one file per interview, or per session
for multi-session interviews — see [steps/import.md](steps/import.md) for the required
file-naming and timestamp format). Then:

```sh
toolkit import
```

Read what it prints: the speaker-role table shows whether your interviewer labels are
configured correctly (fix `config.yaml` → `import:` and re-run if not), and the
narrator-pooling table shows which session files it grouped together.

From here, follow [WORKFLOW.md](WORKFLOW.md).

## If something goes wrong

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md). The golden rule: the toolkit fails loudly and
tells you what to fix; interrupted runs are never lost — run the same command again and it
picks up where it stopped.
