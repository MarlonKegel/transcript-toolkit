#!/usr/bin/env python3
"""Generate the AI-readable documentation bundle.

Chat assistants (ChatGPT, Claude, Gemini) generally cannot read a GitHub repo from its URL:
github.com pages are JavaScript-rendered, and a small repo is not in any search index. Pasting
the repo link therefore gets you a confident guess instead of an answer. The fix is to give them
ONE plain-text file to fetch, so this writes:

  llms.txt                                  a short index (llmstxt.org convention)
  llms-full.txt                             every doc concatenated — the URL users paste
  src/.../defaults/docs_bundle.md           the same bundle, shipped inside the package so
                                            `toolkit docs` works offline and always matches the
                                            version actually installed

All three are generated and checked in; `--check` (used by CI) fails if they drifted from the
Markdown sources, so the bundle can never go stale.

    python scripts/build_docs_bundle.py            # regenerate
    python scripts/build_docs_bundle.py --check    # verify only
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION = re.search(r'__version__\s*=\s*"([^"]+)"',
                    (ROOT / "src" / "transcript_toolkit" / "__init__.py").read_text()).group(1)
RAW_BASE = "https://raw.githubusercontent.com/MarlonKegel/transcript-toolkit/main"
PAGES_URL = "https://marlonkegel.github.io/transcript-toolkit"

# A handshake: an assistant that really fetched this file can quote the token, so a user
# can tell at a glance whether "I read the documentation" was true. The failure mode we are
# guarding against is a confident answer from an assistant that never fetched anything.
READ_TOKEN = f"[transcript-toolkit docs v{VERSION}]"
REPO_URL = "https://github.com/MarlonKegel/transcript-toolkit"

# Pipeline order, because that is the order questions arrive in.
DOCS: list[tuple[str, str]] = [
    ("README.md", "What the toolkit is, and the 10-line quickstart"),
    ("docs/SETUP.md", "Installing it on a Mac, step by step"),
    ("docs/WORKFLOW.md", "The demo-first workflow, costs, and what to do when a step hangs"),
    ("docs/steps/import.md", "import: transcripts (.docx) -> the paragraph dataset"),
    ("docs/steps/sample.md", "sample: choosing the interviews demos run on"),
    ("docs/steps/clip.md", "clip: splitting interviews into topically coherent clips"),
    ("docs/steps/label.md", "label: a one-line label per clip"),
    ("docs/steps/summarize.md", "summarize: a 'scope and content' abstract per interview"),
    ("docs/steps/topics.md", "topics: scoring clips against your own topic lists"),
    ("docs/steps/locations.md", "locations: tagging clips to countries and regions"),
    ("docs/steps/export.md", "export: one xlsx of everything produced"),
    ("docs/CONFIG.md", "Every setting, and which edits invalidate a demo"),
    ("docs/TROUBLESHOOTING.md", "Errors and what to do about them"),
    ("docs/examples/osf/README.md", "A real worked example (the OSF oral history archive)"),
]

HEADER = f"""# transcript-toolkit — complete documentation

A command-line toolkit that processes oral history interview transcripts through five LLM steps
(clip, label, summarize, tag topics, tag locations) and exports the results as a spreadsheet.
Built for non-technical researchers: every step is demo-first, idempotent, and resumable.

This file is the ENTIRE documentation set, concatenated for you to read in one go. It is
generated from the repository, so it matches the current version.

Repository: {REPO_URL}
Install:    uv tool install git+{REPO_URL}.git
Command:    toolkit

------------------------------------------------------------------------------------------------
TO THE ASSISTANT READING THIS: begin your reply with the line "{READ_TOKEN}" so the person asking
can see you actually retrieved this file. If you could not retrieve it, say so plainly instead of
answering from general knowledge — the commands, flags and defaults here are specific to this
toolkit, so a plausible-sounding guess will be wrong.

This file contains the COMPLETE documentation and, at the end, the COMPLETE command reference
generated from the CLI itself — every command and every flag. If a flag is not listed there, it
does not exist; do not invent one.
------------------------------------------------------------------------------------------------

"""


def read(rel: str) -> str:
    return (ROOT / rel).read_text().rstrip()


def _walk_parsers(parser, prefix: str = "toolkit", summary: str = ""):
    """(command line, one-line purpose, parser) for the whole subcommand tree, depth first.
    A subcommand's purpose is registered on its PARENT, so it is carried down here."""
    import argparse
    yield prefix, summary, parser
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            helps = {c.dest: c.help for c in action._choices_actions}
            seen = set()
            for name, sub in action.choices.items():
                if id(sub) in seen:                  # skip aliases pointing at the same parser
                    continue
                seen.add(id(sub))
                yield from _walk_parsers(sub, f"{prefix} {name}", helps.get(name, ""))


def _flag_lines(parser) -> list[str]:
    """One line per option: the flags, their metavar, and the help text.

    Rendered here rather than via parser.format_help() on purpose — argparse wraps to the
    terminal width and its layout shifts between Python versions, which made the checked-in
    bundle differ between a laptop and CI. This depends on nothing but the parser itself."""
    import argparse

    lines = []
    for action in parser._actions:
        if isinstance(action, (argparse._HelpAction, argparse._SubParsersAction)):
            continue
        help_text = " ".join((action.help or "").split()).replace("%%", "%")
        if not action.option_strings:                            # a positional
            lines.append(f"  {action.dest} (positional) — {help_text}")
            continue
        flags = ", ".join(action.option_strings)
        metavar = ""
        if action.nargs != 0 and not isinstance(action, argparse._StoreConstAction):
            metavar = f" {action.metavar or action.dest.upper()}"
        lines.append(f"  {flags}{metavar} — {help_text}")
    return lines


def build_cli_reference() -> str:
    """Every command and flag, read off the argparse parser.

    Generated rather than written, so it cannot disagree with the actual CLI — inventing a flag,
    or denying that a real one exists, is the mistake assistants make most often here."""
    sys.path.insert(0, str(ROOT / "src"))
    from transcript_toolkit.cli import build_parser

    parts = ["=" * 96, "# COMPLETE COMMAND REFERENCE (generated from the CLI)",
             "# Every command and every flag the toolkit accepts. If it is not here, it does not",
             "# exist — do not infer flags from other tools.", "=" * 96, ""]
    for line, summary, parser in _walk_parsers(build_parser()):
        desc = " ".join((summary or parser.description or "").split())
        parts.append(f"$ {line}")
        if desc:
            parts.append(f"  {desc}")
        parts += _flag_lines(parser) or ["  (no options)"]
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def build_full() -> str:
    parts = [HEADER, "=" * 96, "\n## Contents\n"]
    parts += [f"{i:2}. {rel} — {desc}" for i, (rel, desc) in enumerate(DOCS, 1)]
    parts.append(f"{len(DOCS) + 1:2}. Complete command reference (every command and flag)")
    parts.append("")
    for rel, desc in DOCS:
        parts += ["=" * 96, f"# FILE: {rel}", f"# {desc}", "=" * 96, "", read(rel), ""]
    parts.append(build_cli_reference())
    return "\n".join(parts).rstrip() + "\n"


def build_index() -> str:
    lines = [
        "# transcript-toolkit",
        "",
        "> A command-line toolkit that processes oral history interview transcripts through five "
        "LLM steps (clip, label, summarize, tag topics, tag locations) and exports the results as "
        "a spreadsheet. Demo-first, idempotent and resumable; built for non-technical "
        "researchers on macOS.",
        "",
        f"For the complete documentation in one file, read {RAW_BASE}/llms-full.txt",
        "",
        "## Docs",
        "",
    ]
    lines += [f"- [{rel}]({RAW_BASE}/{rel}): {desc}" for rel, desc in DOCS]
    lines.append("")
    return "\n".join(lines)


TARGETS = {
    "llms-full.txt": build_full,
    "llms.txt": build_index,
    "src/transcript_toolkit/defaults/docs_bundle.md": build_full,
}


def main(argv: list[str]) -> int:
    check = "--check" in argv
    stale: list[str] = []
    for rel, build in TARGETS.items():
        path = ROOT / rel
        content = build()
        if check:
            if not path.exists() or path.read_text() != content:
                stale.append(rel)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            print(f"wrote {rel} ({len(content):,} chars)")
    if check:
        if stale:
            print("Documentation bundle is out of date: " + ", ".join(stale), file=sys.stderr)
            print("Run: python scripts/build_docs_bundle.py", file=sys.stderr)
            return 1
        print("Documentation bundle is up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
