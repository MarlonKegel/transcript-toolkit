"""Parser-level tests: every --help must render, and the batch flag must sit on exactly the
steps that can actually use the Batch API."""
import pytest

from transcript_toolkit.cli import build_parser

# every command path in the CLI, as argv prefixes
COMMANDS = [
    [], ["init"], ["app"], ["update"], ["docs"], ["import"], ["sample"],
    ["clip"], ["clip", "annotate"], ["clip", "preview"],
    ["label"], ["label", "annotate"], ["label", "preview"],
    ["summarize"], ["summarize", "annotate"],
    ["topics"], ["topics", "tag"], ["topics", "rollup"], ["topics", "thresholds"],
    ["topics", "annotate"], ["topics", "preview"],
    ["locations"], ["locations", "tag"], ["locations", "map"], ["locations", "rollup"],
    ["locations", "thresholds"], ["locations", "annotate"], ["locations", "survey"],
    ["locations", "preview"],
    ["export"], ["cost"], ["status"],
]

# steps that can go to the Batch API. Clip is the odd one: its chunks are sequential (chunk
# N's prompt is built from chunk N-1's output), so it batches in WAVES — one wave per chunk
# depth, each up to 24h — and the run's own prompt says so before anything is spent.
BATCHABLE = [["clip"], ["label"], ["summarize"], ["topics", "tag"], ["locations", "tag"]]


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


def test_every_command_is_covered_here():
    """COMMANDS is written out by hand so the --help test can name each one; this keeps it
    honest when a command is added."""
    import argparse

    def walk(parser, prefix=()):
        yield list(prefix)
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                seen = set()
                for name, sub in action.choices.items():
                    if id(sub) not in seen:          # aliases point at the same parser
                        seen.add(id(sub))
                        yield from walk(sub, (*prefix, name))

    real = {tuple(c) for c in walk(build_parser())}
    listed = {tuple(c) for c in COMMANDS}
    assert real - listed == set(), f"not covered by test_help_renders: {sorted(real - listed)}"


def test_update_has_an_upgrade_alias():
    """`toolkit upgrade` is what people type first; it must not error."""
    parser = build_parser()
    for name in ("update", "upgrade"):
        assert parser.parse_args([name]).func.__name__ == "cmd_update"


def test_init_takes_a_directory_or_a_name(tmp_path, capsys, monkeypatch):
    """Either one is enough, and the other follows from it — the app asks for the name, the
    terminal usually gives the folder."""
    from transcript_toolkit.cli import cmd_init
    from transcript_toolkit.core.config import project_name
    from transcript_toolkit.project import find_project

    monkeypatch.chdir(tmp_path)
    cmd_init(build_parser().parse_args(["init", "--name", "Anderson Family Oral History"]))
    made = find_project(str(tmp_path / "anderson-family-oral-history"))
    assert project_name(made) == "Anderson Family Oral History"
    assert "cd anderson-family-oral-history" in capsys.readouterr().out

    cmd_init(build_parser().parse_args(["init", "my-archive"]))
    assert project_name(find_project(str(tmp_path / "my-archive"))) == "My Archive"


def test_init_with_neither_says_what_to_type():
    from transcript_toolkit.cli import cmd_init
    from transcript_toolkit.errors import ToolkitError

    with pytest.raises(ToolkitError, match="Usage: toolkit init"):
        cmd_init(build_parser().parse_args(["init"]))
