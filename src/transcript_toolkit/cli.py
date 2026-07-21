"""`toolkit` command-line interface.

Thin dispatch only: subcommand handlers resolve the workspace, load config, and call a function
in `steps/`. Step functions never parse arguments or exit — they raise ToolkitError, caught once
here and printed without a traceback.
"""
from __future__ import annotations

import argparse
import sys

from . import __version__
from .errors import ToolkitError


def _common() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--project", metavar="DIR", default=None,
                        help="workspace directory (default: walk up from the current directory)")
    return common


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="toolkit",
        description="Process oral history interview transcripts: clip, label, summarize, "
                    "tag topics and locations, export.",
    )
    parser.add_argument("--version", action="version", version=f"transcript-toolkit {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    common = _common()

    p = sub.add_parser("init", parents=[common],
                       help="create a new project workspace (or restore a default prompt)")
    p.add_argument("dir", nargs="?", default=None, help="directory to create")
    p.add_argument("--reset-prompt", metavar="NAME", default=None,
                   help="restore one prompt in the current workspace to the packaged default")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("import", parents=[common],
                       help="parse the .docx transcripts in data/ into the paragraph dataset")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("status", parents=[common], help="show corpus, per-step demo/run state")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.set_defaults(func=cmd_status)

    return parser


def cmd_init(args) -> None:
    from .project import find_project, init_project, reset_prompt

    if args.reset_prompt is not None:
        if args.dir is not None:
            raise ToolkitError("Pass either a directory or --reset-prompt, not both.")
        project = find_project(args.project)
        dest = reset_prompt(project, args.reset_prompt)
        print(f"Restored default prompt: {dest}")
        return
    if args.dir is None:
        raise ToolkitError("Usage: toolkit init <dir>   (or: toolkit init --reset-prompt <name>)")
    project = init_project(args.dir)
    print(f"Created workspace: {project.root}")
    print("\nNext steps:")
    print(f"  1. Put your OpenAI API key in {project.root / '.env'}")
    print(f"  2. Drop your transcript .docx files into {project.data_dir}/")
    print("  3. Run: toolkit import")


def cmd_import(args) -> None:
    from .project import find_project
    from .steps.import_ import run_import

    run_import(find_project(args.project))


def cmd_status(args) -> None:
    from .project import find_project
    from .steps.status import run_status

    run_status(find_project(args.project), as_json=args.json)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    try:
        args.func(args)
        return 0
    except ToolkitError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
