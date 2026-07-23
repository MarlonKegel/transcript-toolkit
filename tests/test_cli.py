"""Parser-level tests: every --help must render, and the batch flag must sit on exactly the
steps that can actually use the Batch API."""
import pytest

from transcript_toolkit.cli import build_parser

# every command path in the CLI, as argv prefixes
COMMANDS = [
    [], ["init"], ["import"], ["sample"],
    ["clip"], ["clip", "annotate"], ["clip", "preview"],
    ["label"], ["label", "annotate"], ["label", "preview"],
    ["summarize"], ["summarize", "annotate"],
    ["topics", "tag"], ["topics", "rollup"], ["topics", "thresholds"],
    ["topics", "annotate"], ["topics", "preview"],
    ["locations", "tag"], ["locations", "map"], ["locations", "rollup"],
    ["locations", "thresholds"], ["locations", "annotate"], ["locations", "survey"],
    ["locations", "preview"],
    ["export"], ["cost"], ["status"],
]

# steps whose units are all planned before any call, so they can go to the Batch API
BATCHABLE = [["label"], ["summarize"], ["topics", "tag"], ["locations", "tag"]]


@pytest.mark.parametrize("argv", COMMANDS, ids=lambda a: " ".join(a) or "root")
def test_help_renders(argv, capsys):
    """argparse %-expands help strings — an unescaped '%' (e.g. '50%-off') raises only when the
    help is actually formatted, which no other test does."""
    with pytest.raises(SystemExit) as e:
        build_parser().parse_args([*argv, "--help"])
    assert e.value.code == 0
    assert capsys.readouterr().out.strip()


@pytest.mark.parametrize("argv", BATCHABLE, ids=lambda a: " ".join(a))
def test_batchable_steps_take_batch_flag(argv):
    parser = build_parser()
    assert parser.parse_args([*argv, "--batch"]).batch is True
    assert parser.parse_args([*argv, "--no-batch"]).batch is False
    assert parser.parse_args(argv).batch is None          # unset -> ask at the prompt


def test_clip_has_no_batch_flag():
    """Clip's chunks are sequential within an interview (chunk N's prompt is built from chunk
    N-1's output), so its calls cannot all be submitted up front."""
    with pytest.raises(SystemExit):
        build_parser().parse_args(["clip", "--batch"])
