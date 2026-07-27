"""`toolkit docs` — hand the documentation to an AI chat (or just read it).

Chat assistants can't reliably read the repo from its GitHub URL — those pages are
JavaScript-rendered and a small repo isn't in any search index, so the assistant answers from
general knowledge and gets the details wrong. The bundle ships inside the package, so this works
with no network and always describes the version actually installed.
"""
from __future__ import annotations

from importlib import resources
from pathlib import Path

from .. import __version__
from ..errors import ToolkitError

DEFAULT_FILENAME = "transcript-toolkit-docs.md"
BUNDLE_URL = ("https://raw.githubusercontent.com/MarlonKegel/transcript-toolkit/"
              "main/llms-full.txt")


def bundle_text() -> str:
    src = resources.files("transcript_toolkit") / "defaults" / "docs_bundle.md"
    if not src.is_file():
        raise ToolkitError(
            "The packaged documentation bundle is missing from this install. "
            f"Read the docs online instead: {BUNDLE_URL}")
    return src.read_text()


def run_docs(out: str | None = None, to_stdout: bool = False) -> None:
    text = bundle_text()
    if to_stdout:
        print(text)
        return
    path = Path(out or DEFAULT_FILENAME).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    print(f"Wrote the complete documentation (transcript-toolkit {__version__}) to:\n  {path}\n")
    print("Drag this file into ChatGPT / Claude / Gemini and ask your question. That always\n"
          "works — no fetching involved.\n")
    print(f"Or paste this link instead: {BUNDLE_URL}")
    print(f"If you do, check the reply starts with \"[transcript-toolkit docs v{__version__}]\" — "
          f"without it\nthe assistant did not read the docs and is guessing.")
