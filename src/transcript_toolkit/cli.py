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
    # SUPPRESS (not None): with nested subparsers, an inner parser's default would otherwise
    # clobber a --project given before the subcommand. Read via _project(args).
    common.add_argument("--project", metavar="DIR", default=argparse.SUPPRESS,
                        help="workspace directory (default: walk up from the current directory)")
    return common


def _project(args):
    from .project import find_project
    return find_project(getattr(args, "project", None))


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

    p = sub.add_parser("sample", parents=[common],
                       help="draw the demo sample of interviews used by clip/label demo runs")
    p.add_argument("--n", type=int, default=None, help="sample size (default 5)")
    p.add_argument("--seed", type=int, default=0, help="random seed (default 0)")
    p.add_argument("--interviews", metavar="IDS", default=None,
                   help="comma-separated interview ids to use instead of a random draw")
    p.set_defaults(func=cmd_sample)

    p = sub.add_parser("summarize", parents=[common],
                       help="one 'scope and content' abstract per interview (demo-first)")
    p.add_argument("--demo", action="store_true", help="summarize a small sample and write the review md only")
    p.add_argument("--interview", metavar="KEYS", default=None,
                   help="comma-separated interview keys (subset run, merged into the deliverable)")
    p.add_argument("--pool-sessions", action=argparse.BooleanOptionalAction, default=None,
                   help="pool a narrator's sessions into one summary (default: config)")
    p.add_argument("--yes", action="store_true", help="skip the cost confirmation prompt")
    p.add_argument("--skip-demo-check", action="store_true",
                   help="bypass the demo gate (dev use only)")
    p.set_defaults(func=cmd_summarize)
    ssub = p.add_subparsers(dest="action", metavar="")
    pa = ssub.add_parser("annotate", parents=[common],
                         help="re-render the review md from the existing deliverable")
    pa.set_defaults(func=cmd_summarize_annotate)

    p = sub.add_parser("status", parents=[common], help="show corpus, per-step demo/run state")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.set_defaults(func=cmd_status)

    return parser


def cmd_init(args) -> None:
    from .project import init_project, reset_prompt

    if args.reset_prompt is not None:
        if args.dir is not None:
            raise ToolkitError("Pass either a directory or --reset-prompt, not both.")
        dest = reset_prompt(_project(args), args.reset_prompt)
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
    from .steps.import_ import run_import

    run_import(_project(args))


def cmd_sample(args) -> None:
    from .core.sampling import DEFAULT_N, draw_interview_sample

    explicit = [s.strip() for s in args.interviews.split(",") if s.strip()] if args.interviews else None
    sample = draw_interview_sample(_project(args), n=args.n or DEFAULT_N,
                                   seed=args.seed, explicit=explicit)
    print(f"Demo sample ({len(sample)} interviews):")
    for iid in sample:
        print(f"  {iid}")


def cmd_summarize(args) -> None:
    from .steps.summarize import run_summarize

    interviews = ([s.strip() for s in args.interview.split(",") if s.strip()]
                  if args.interview else None)
    run_summarize(_project(args), demo=args.demo, interviews=interviews,
                  pool_sessions=args.pool_sessions, yes=args.yes,
                  skip_demo_check=args.skip_demo_check)


def cmd_summarize_annotate(args) -> None:
    from .steps.summarize import annotate_summaries

    annotate_summaries(_project(args))


def cmd_status(args) -> None:
    from .steps.status import run_status

    run_status(_project(args), as_json=args.json)


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
