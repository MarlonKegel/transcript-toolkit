"""Messages are written for the person using the toolkit, not for whoever built it.

A message that justifies a design decision ("replacing it silently would be worse", "this is
single-slot on purpose") reads to a curator as a comment on something they did wrong, and the
next thing that happens is an email asking what they should have done instead. The reasoning
belongs in comments and docstrings — where all of it still is, and where this test does not
look.
"""
import ast
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src" / "transcript_toolkit"

# Phrases that only ever appear when a message has drifted into explaining itself to its author.
ARCHITECT_SPEAK = ("would be worse", "on purpose", "deliberately", "by design",
                   "for a reason", "intentionally")


def literals(path: Path):
    """Every string literal in a file that is not a docstring, with its line number."""
    tree = ast.parse(path.read_text())
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            found = ast.get_docstring(node, clean=False)
            if found is not None:
                docstrings.add(found)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and node.value not in docstrings:
            yield node.lineno, node.value


PY_FILES = sorted(SRC.rglob("*.py"))


@pytest.mark.parametrize("path", PY_FILES, ids=lambda p: str(p.relative_to(SRC)))
def test_no_message_explains_itself_to_its_author(path):
    offenders = [(line, text.strip()[:120], phrase)
                 for line, text in literals(path)
                 for phrase in ARCHITECT_SPEAK if phrase in text.lower()]
    assert not offenders, "\n".join(
        f"{path.relative_to(SRC)}:{line}: {phrase!r} in {text!r}"
        for line, text, phrase in offenders)


def test_dropping_a_known_filename_replaces_and_says_which(tmp_path):
    """A corrected transcript arrives under the filename it always had. The drop must replace
    the old version — and report what it did, so the page can tell the curator to import
    again rather than leaving a stale dataset behind a fresh file."""
    from transcript_toolkit.app import workspaces
    from transcript_toolkit.project import init_project

    project = init_project(str(tmp_path / "ws"))
    path, outcome = workspaces.add_transcript(project, "Person_SYNC.docx", b"x")
    assert outcome == "added"
    path, outcome = workspaces.add_transcript(project, "Person_SYNC.docx", b"x")
    assert outcome == "unchanged" and path.read_bytes() == b"x"
    path, outcome = workspaces.add_transcript(project, "Person_SYNC.docx", b"y")
    assert outcome == "replaced" and path.read_bytes() == b"y"
