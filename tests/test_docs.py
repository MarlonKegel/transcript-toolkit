"""The documentation bundle: shipped with the package, and never stale."""
import subprocess
import sys
from pathlib import Path

import pytest

from transcript_toolkit.steps.docs import DEFAULT_FILENAME, bundle_text, run_docs

REPO = Path(__file__).resolve().parent.parent


def test_bundle_ships_with_the_package_and_has_every_doc():
    text = bundle_text()
    assert "transcript-toolkit — complete documentation" in text
    for doc in ("docs/SETUP.md", "docs/WORKFLOW.md", "docs/steps/topics.md",
                "docs/steps/sample.md", "docs/TROUBLESHOOTING.md", "docs/CONFIG.md"):
        assert f"# FILE: {doc}" in text, doc
    # content, not just headers
    assert "xcode-select --install" in text            # SETUP's first step
    assert "--set collection" in text                  # the new topics flow


def test_bundle_carries_the_generated_command_reference():
    """Every command and flag, taken from argparse itself. Generated rather than written, so it
    cannot drift from the CLI — inventing or denying a flag is the mistake assistants make most."""
    text = bundle_text()
    for cmd in ("$ toolkit sample --help", "$ toolkit topics tag --help",
                "$ toolkit locations survey --help", "$ toolkit clip preview --help"):
        assert cmd in text, cmd
    assert "--interviews IDS" in text                  # the flag an assistant claimed didn't exist
    assert "--no-batch" in text and "--skip-demo-check" in text


def test_bundle_asks_for_proof_of_reading():
    """A reader that really fetched the file can quote the token, so 'I read the docs' is
    checkable — the observed failure was an assistant answering confidently without fetching."""
    from transcript_toolkit import __version__
    text = bundle_text()
    assert f"[transcript-toolkit docs v{__version__}]" in text
    assert text.index("TO THE ASSISTANT READING THIS") < 2000    # near the top, before any truncation


def test_docs_command_writes_a_droppable_file(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    run_docs()
    written = tmp_path / DEFAULT_FILENAME
    assert written.exists() and written.read_text() == bundle_text()
    out = capsys.readouterr().out
    assert "Drag this file into ChatGPT" in out         # the method that needs no fetching
    assert "llms-full.txt" in out                       # the link, as the alternative
    assert "is guessing" in out                         # how to spot an assistant that bluffed


def test_docs_command_can_print_and_target_a_path(tmp_path, monkeypatch, capsys):
    run_docs(out=str(tmp_path / "sub" / "d.md"))
    assert (tmp_path / "sub" / "d.md").exists()        # parent dir created
    capsys.readouterr()
    run_docs(to_stdout=True)
    assert "# FILE: docs/SETUP.md" in capsys.readouterr().out


@pytest.mark.skipif(not (REPO / "scripts" / "build_docs_bundle.py").exists(),
                    reason="running against an installed copy, not the repo")
def test_checked_in_bundle_is_current():
    """CI runs this too: editing a doc without regenerating would leave the link users paste
    into ChatGPT out of date."""
    r = subprocess.run([sys.executable, "scripts/build_docs_bundle.py", "--check"],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
