"""`toolkit` command-line interface.

Thin dispatch only: subcommand handlers resolve the workspace, load config, and call a function
in `steps/`. Step functions never parse arguments or exit — they raise ToolkitError, caught once
here and printed without a traceback.
"""
from __future__ import annotations

import argparse
import sys

from . import __version__
from .app import DEFAULT_PORT
from .errors import ToolkitError


DEFAULT_DOCS_FILENAME = "transcript-toolkit-docs.md"

SET_HELP = ("which topic set to use — the name of your topic spreadsheet in topics/ "
            "(topics/collection.xlsx -> --set collection). Required: there is no default.")

BATCH_HELP = ("run the full corpus on the 50%%-off Batch API (slower: up to 24h) or force it off; "
              "omit to be asked, with both cost estimates, at the confirmation prompt")


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


def _compare_flags(parser: argparse.ArgumentParser) -> None:
    """What the two `thresholds` decision aids should draw. Omit them all and the aid uses what
    advanced/<step>.yaml says under `compare`."""
    parser.add_argument("--bins", metavar="N,N", default=None,
                        help="how many rarity bins to compare, e.g. --bins 5,9")
    parser.add_argument("--ranges", metavar="LO-HI,LO-HI", default=None,
                        help="lowest-highest threshold per range, e.g. --ranges 10-30,20-40")
    parser.add_argument("--flat", metavar="PCT,PCT", default=None,
                        help="single thresholds to compare for the flat method, e.g. --flat 20,30")


def _compare(args) -> dict:
    from .core import thresholds

    return {"bins": thresholds.parse_bins(args.bins) if args.bins else None,
            "ranges": thresholds.parse_ranges(args.ranges) if args.ranges else None,
            "flat": thresholds.parse_flat(args.flat) if args.flat else None}


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
    p.add_argument("--name", metavar="NAME", default=None,
                   help="what the project is called (config.yaml project.name, shown in the app). "
                        "Give a directory and the name is derived from it; give a name and the "
                        "directory is derived from that.")
    p.add_argument("--reset-prompt", metavar="NAME", default=None,
                   help="restore one prompt in the current workspace to the packaged default")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("app", parents=[common],
                       help="open the toolkit's window in your browser (the point-and-click app)")
    p.add_argument("--port", type=int, default=None,
                   help=f"port to serve on (default {DEFAULT_PORT})")
    p.add_argument("--no-browser", dest="open_browser", action="store_false",
                   help="start the server without opening a browser window")
    p.add_argument("--from-launcher", action="store_true",
                   help=argparse.SUPPRESS)          # set by the generated Mac launcher app
    p.add_argument("--install-launcher", action="store_true",
                   help="create the double-clickable app in your Applications folder (macOS)")
    p.set_defaults(func=cmd_app)

    p = sub.add_parser("update", parents=[common], aliases=["upgrade"],
                       help="install the latest version of the toolkit")
    p.set_defaults(func=cmd_update)

    p = sub.add_parser("docs", parents=[common],
                       help="save the full documentation to a file, to ask an AI about it")
    p.add_argument("--out", metavar="FILE", default=None,
                   help=f"where to write it (default: ./{DEFAULT_DOCS_FILENAME})")
    p.add_argument("--print", dest="to_stdout", action="store_true",
                   help="print to the terminal instead of writing a file")
    p.set_defaults(func=cmd_docs)

    p = sub.add_parser("import", parents=[common],
                       help="parse the .docx transcripts in data/ into the paragraph dataset")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("sample", parents=[common],
                       help="draw the demo sample of interviews used by clip/label demo runs")
    p.add_argument("--n", type=int, default=None, help="sample size (default 5, allowed 3-10)")
    p.add_argument("--seed", type=int, default=0, help="random seed (default 0)")
    p.add_argument("--interviews", metavar="IDS", default=None,
                   help="comma-separated interview ids to put in the sample. With --n, the rest "
                        "of the sample is drawn at random from the others; without it, the "
                        "sample is exactly these.")
    p.set_defaults(func=cmd_sample)

    for step, help_txt, run_fn, annotate_fn, preview_fn, preview_help in (
            ("clip", "split each interview into clips (demo-first)",
             cmd_clip, cmd_clip_annotate, cmd_clip_preview,
             "preview the chunking of every interview (no API)"),
            ("label", "one-line label per clip (demo-first)",
             cmd_label, cmd_label_annotate, cmd_label_preview,
             "preview the clip batching (no API)")):
        p = sub.add_parser(step, parents=[common], help=help_txt)
        p.add_argument("--demo", action="store_true",
                       help="run on the `toolkit sample` interviews, review pages only")
        p.add_argument("--interview", metavar="IDS", default=None,
                       help="comma-separated interview ids (subset run, merged)")
        p.add_argument("--yes", action="store_true", help="skip the cost confirmation prompt")
        p.add_argument("--skip-demo-check", action="store_true",
                       help="bypass the demo gate (dev use only)")
        if step == "label":     # clip cannot batch: its chunks are sequential within an interview
            p.add_argument("--batch", action=argparse.BooleanOptionalAction, default=None,
                           help=BATCH_HELP)
        p.set_defaults(func=run_fn)
        csub = p.add_subparsers(dest="action", metavar="")
        pa = csub.add_parser("annotate", parents=[common],
                             help="re-render the per-interview review pages from the deliverable")
        pa.set_defaults(func=annotate_fn)
        pa = csub.add_parser("preview", parents=[common], help=preview_help)
        pa.set_defaults(func=preview_fn)

    p = sub.add_parser("summarize", parents=[common],
                       help="one 'scope and content' abstract per interview (demo-first)")
    p.add_argument("--demo", action="store_true", help="summarize a small sample and write the review page only")
    p.add_argument("--interview", metavar="KEYS", default=None,
                   help="comma-separated interview keys (subset run, merged into the deliverable)")
    p.add_argument("--pool-sessions", action=argparse.BooleanOptionalAction, default=None,
                   help="pool a narrator's sessions into one summary (default: config)")
    p.add_argument("--yes", action="store_true", help="skip the cost confirmation prompt")
    p.add_argument("--skip-demo-check", action="store_true",
                   help="bypass the demo gate (dev use only)")
    p.add_argument("--batch", action=argparse.BooleanOptionalAction, default=None, help=BATCH_HELP)
    p.set_defaults(func=cmd_summarize)
    ssub = p.add_subparsers(dest="action", metavar="")
    pa = ssub.add_parser("annotate", parents=[common],
                         help="re-render the review page from the existing deliverable")
    pa.set_defaults(func=cmd_summarize_annotate)

    p = sub.add_parser("topics", parents=[common],
                       help="score clips against your topic list(s), roll up to interview tags")
    tsub = p.add_subparsers(dest="action", metavar="<action>", required=True)

    pt = tsub.add_parser("tag", parents=[common], help="tag clips (demo-first)")
    pt.add_argument("--set", dest="set_name", default=None, help=SET_HELP)
    pt.add_argument("--demo", action="store_true", help="tag a spread sample of clips, review page only")
    pt.add_argument("--sample", dest="sample_n", type=int, default=None,
                    help="override the demo sample size")
    pt.add_argument("--seed", type=int, default=None, help="override the demo sample seed")
    pt.add_argument("--interview", metavar="IDS", default=None,
                    help="comma-separated interview ids (subset run, merged)")
    pt.add_argument("--justify", action=argparse.BooleanOptionalAction, default=None,
                    help="per-topic justifications (default: on for demos, off for full runs)")
    pt.add_argument("--batch", action=argparse.BooleanOptionalAction, default=None, help=BATCH_HELP)
    pt.add_argument("--yes", action="store_true", help="skip the cost confirmation prompt")
    pt.add_argument("--skip-demo-check", action="store_true", help="bypass the demo gate (dev use only)")
    pt.set_defaults(func=cmd_topics_tag)

    pt = tsub.add_parser("preview", parents=[common], help="print the exact request for one clip (no API)")
    pt.add_argument("--set", dest="set_name", default=None, help=SET_HELP)
    pt.add_argument("--clip", default=None, help="clip id (default: first clip)")
    pt.set_defaults(func=cmd_topics_preview)

    pt = tsub.add_parser("rollup", parents=[common], help="clip tags -> interview tags")
    pt.add_argument("--set", dest="set_name", default=None, help=SET_HELP)
    pt.set_defaults(func=cmd_topics_rollup)

    pt = tsub.add_parser("thresholds", parents=[common],
                         help="compare rollup rules before choosing one (decision aid)")
    pt.add_argument("--set", dest="set_name", default=None, help=SET_HELP)
    _compare_flags(pt)
    pt.set_defaults(func=cmd_topics_thresholds)

    pt = tsub.add_parser("annotate", parents=[common], help="re-render the per-interview review pages")
    pt.add_argument("--set", dest="set_name", default=None, help=SET_HELP)
    pt.set_defaults(func=cmd_topics_annotate)

    p = sub.add_parser("locations", parents=[common],
                       help="tag clips to countries/regions, map, roll up to interview tags")
    lsub = p.add_subparsers(dest="action", metavar="<action>", required=True)

    pl = lsub.add_parser("tag", parents=[common], help="tag clips (demo-first)")
    pl.add_argument("--demo", action="store_true", help="tag a spread sample of clips, review page only")
    pl.add_argument("--sample", dest="sample_n", type=int, default=None,
                    help="override the demo sample size")
    pl.add_argument("--seed", type=int, default=None, help="override the demo sample seed")
    pl.add_argument("--interview", metavar="IDS", default=None,
                    help="comma-separated interview ids (subset run, merged)")
    pl.add_argument("--justify", action=argparse.BooleanOptionalAction, default=None,
                    help="per-place justifications (default: on for demos, off for full runs)")
    pl.add_argument("--batch", action=argparse.BooleanOptionalAction, default=None, help=BATCH_HELP)
    pl.add_argument("--yes", action="store_true", help="skip the cost confirmation prompt")
    pl.add_argument("--skip-demo-check", action="store_true", help="bypass the demo gate (dev use only)")
    pl.set_defaults(func=cmd_locations_tag)

    pl = lsub.add_parser("preview", parents=[common], help="print the exact request for one clip (no API)")
    pl.add_argument("--clip", default=None, help="clip id (default: first clip)")
    pl.set_defaults(func=cmd_locations_preview)

    pl = lsub.add_parser("map", parents=[common], help="expand regions to countries, apply the label canon")
    pl.set_defaults(func=cmd_locations_map)

    pl = lsub.add_parser("rollup", parents=[common], help="clip tags -> interview tags (hybrid scheme)")
    pl.set_defaults(func=cmd_locations_rollup)

    pl = lsub.add_parser("thresholds", parents=[common],
                         help="compare rollup rules before choosing one (decision aid)")
    _compare_flags(pl)
    pl.set_defaults(func=cmd_locations_thresholds)

    pl = lsub.add_parser("annotate", parents=[common], help="re-render the review page")
    pl.set_defaults(func=cmd_locations_annotate)

    pl = lsub.add_parser("survey", parents=[common],
                         help="offline NER survey of place mentions (needs the [survey] extra)")
    pl.set_defaults(func=cmd_locations_survey)

    p = sub.add_parser("export", parents=[common],
                       help="build one xlsx of everything produced so far")
    p.add_argument("--out", metavar="FILE", default=None,
                   help="output path (default: outputs/export.xlsx)")
    # Not argparse `choices`: the mode list lives in steps/export.py, and importing that here
    # would pull pandas into every `toolkit` invocation. run_export validates and names them.
    p.add_argument("--locations", metavar="MODE", default=None,
                   help="override config.yaml export.locations — countries (direct only) | "
                        "countries_and_regions (plus a Regions column) | countries_incl_regions "
                        "(regions mapped down into the countries column)")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("cost", parents=[common],
                       help="LLM spend so far, from the per-call caches")
    p.add_argument("step", nargs="?", default=None,
                   help="one step's caches only (e.g. summarize, topics, locations)")
    p.add_argument("--to-n", type=int, default=None, metavar="N",
                   help="extrapolate the mean per-call cost to N calls")
    p.set_defaults(func=cmd_cost)

    p = sub.add_parser("status", parents=[common], help="show corpus, per-step demo/run state")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.set_defaults(func=cmd_status)

    return parser


def cmd_init(args) -> None:
    from .project import folder_name, init_project, reset_prompt

    if args.reset_prompt is not None:
        if args.dir is not None:
            raise ToolkitError("Pass either a directory or --reset-prompt, not both.")
        dest = reset_prompt(_project(args), args.reset_prompt)
        print(f"Restored default prompt: {dest}")
        return
    if args.dir is None and args.name is None:
        raise ToolkitError("Usage: toolkit init <dir>   (or: toolkit init --name \"My Project\", "
                           "or: toolkit init --reset-prompt <name>)")
    import shlex

    # One of the two is typed and the other follows from it, so a project is never called one
    # thing on disk and another thing on screen.
    target = args.dir or folder_name(args.name)
    project = init_project(target, name=args.name)
    print(f"Created workspace: {project.root}")
    print("\nNext steps:")
    print(f"  1. Go into the workspace:  cd {shlex.quote(target)}")
    print("  2. Add your OpenAI API key to the .env file there  (on Mac: open -e .env)")
    print("  3. Drop your transcript .docx files into data/")
    print("  4. Run: toolkit import")
    print("\n(Run toolkit commands from inside the workspace — they find it automatically.)")


def cmd_app(args) -> None:
    port = args.port or DEFAULT_PORT

    if args.install_launcher:
        from .app.launcher import install_launcher

        from .app.launcher import where_to_find

        path = install_launcher(port=None if port == DEFAULT_PORT else port)
        print(f"Created {path}")
        print(f"\n{where_to_find(path)}")
        print("Double-click it, and drag it to the Dock if you want it there. From then on "
              "that is how you start the toolkit.")
        return

    from .app.server import serve

    serve(project=getattr(args, "project", None), port=port,
          open_browser=args.open_browser, from_launcher=args.from_launcher)


def cmd_update(args) -> None:
    from .core.update import run_update

    run_update()


def cmd_docs(args) -> None:
    from .steps.docs import run_docs

    run_docs(out=args.out, to_stdout=args.to_stdout)


def cmd_import(args) -> None:
    from .steps.import_ import run_import

    run_import(_project(args))


def cmd_sample(args) -> None:
    from .core.sampling import DEFAULT_N, check_size, draw_interview_sample
    from .core.tables import load_paragraphs

    project = _project(args)
    explicit = [s.strip() for s in args.interviews.split(",") if s.strip()] if args.interviews else None
    # Naming more interviews than --n asks for means you want them all, so the size to check is
    # the larger of the two.
    wanted = max(args.n or 0, len(explicit or [])) or DEFAULT_N
    check_size(wanted, load_paragraphs(project)["interview_id"].nunique())
    sample = draw_interview_sample(project, n=args.n, seed=args.seed, explicit=explicit)
    print(f"Demo sample ({len(sample)} interviews):")
    for iid in sample:
        print(f"  {iid}")


def _split_interviews(args):
    raw = getattr(args, "interview", None)
    return [s.strip() for s in raw.split(",") if s.strip()] if raw else None


def cmd_clip(args) -> None:
    from .steps.clip import run_clip

    run_clip(_project(args), demo=args.demo, interviews=_split_interviews(args),
             yes=args.yes, skip_demo_check=args.skip_demo_check)


def cmd_clip_annotate(args) -> None:
    from .steps.clip import annotate_clips

    annotate_clips(_project(args))


def cmd_clip_preview(args) -> None:
    from .steps.clip import preview_chunks

    preview_chunks(_project(args))


def cmd_label(args) -> None:
    from .steps.label import run_label

    run_label(_project(args), demo=args.demo, interviews=_split_interviews(args),
              yes=args.yes, skip_demo_check=args.skip_demo_check, batch=args.batch)


def cmd_label_annotate(args) -> None:
    from .steps.label import annotate_labels

    annotate_labels(_project(args))


def cmd_label_preview(args) -> None:
    from .steps.label import preview_batches

    preview_batches(_project(args))


def cmd_summarize(args) -> None:
    from .steps.summarize import run_summarize

    interviews = ([s.strip() for s in args.interview.split(",") if s.strip()]
                  if args.interview else None)
    run_summarize(_project(args), demo=args.demo, interviews=interviews,
                  pool_sessions=args.pool_sessions, yes=args.yes,
                  skip_demo_check=args.skip_demo_check, batch=args.batch)


def cmd_summarize_annotate(args) -> None:
    from .steps.summarize import annotate_summaries

    annotate_summaries(_project(args))


def cmd_topics_tag(args) -> None:
    from .steps.topics import run_topics_tag

    interviews = ([s.strip() for s in args.interview.split(",") if s.strip()]
                  if args.interview else None)
    run_topics_tag(_project(args), set_name=args.set_name, demo=args.demo,
                   sample_n=args.sample_n, seed=args.seed, interviews=interviews,
                   justify=args.justify, yes=args.yes, skip_demo_check=args.skip_demo_check,
                   batch=args.batch)


def cmd_topics_preview(args) -> None:
    from .steps.topics import preview_call

    preview_call(_project(args), set_name=args.set_name, clip_id=args.clip)


def cmd_topics_rollup(args) -> None:
    from .steps.topics import run_topics_rollup

    run_topics_rollup(_project(args), set_name=args.set_name)


def cmd_topics_thresholds(args) -> None:
    from .steps.topics import run_topics_thresholds

    run_topics_thresholds(_project(args), set_name=args.set_name, **_compare(args))


def cmd_topics_annotate(args) -> None:
    from .steps.topics import annotate_topics

    annotate_topics(_project(args), set_name=args.set_name)


def cmd_locations_tag(args) -> None:
    from .steps.locations import run_locations_tag

    interviews = ([s.strip() for s in args.interview.split(",") if s.strip()]
                  if args.interview else None)
    run_locations_tag(_project(args), demo=args.demo, sample_n=args.sample_n, seed=args.seed,
                      interviews=interviews, justify=args.justify, batch=args.batch,
                      yes=args.yes, skip_demo_check=args.skip_demo_check)


def cmd_locations_preview(args) -> None:
    from .steps.locations import preview_call

    preview_call(_project(args), clip_id=args.clip)


def cmd_locations_map(args) -> None:
    from .steps.locations import run_locations_map

    run_locations_map(_project(args))


def cmd_locations_rollup(args) -> None:
    from .steps.locations import run_locations_rollup

    run_locations_rollup(_project(args))


def cmd_locations_thresholds(args) -> None:
    from .steps.locations import run_locations_thresholds

    run_locations_thresholds(_project(args), **_compare(args))


def cmd_locations_annotate(args) -> None:
    from .steps.locations import annotate_locations

    annotate_locations(_project(args))


def cmd_locations_survey(args) -> None:
    from .steps.locations import run_locations_survey

    run_locations_survey(_project(args))


def cmd_export(args) -> None:
    from .steps.export import run_export

    run_export(_project(args), out=args.out, locations=args.locations)


def cmd_cost(args) -> None:
    from .steps.cost import run_cost

    run_cost(_project(args), step=args.step, to_n=args.to_n)


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
    except ToolkitError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:               # Ctrl-C on a stuck call is a documented recovery
        print("\nInterrupted. Finished calls are cached — re-run the same command to continue "
              "from where it stopped.", file=sys.stderr)
        return 130
    _print_update_notice()
    return 0


def _print_update_notice() -> None:
    """Shown last, after a command's own output, so it is the thing left on screen. Best-effort
    and cached for a day — see core/update.py."""
    from .core.update import print_update_notice
    print_update_notice()


if __name__ == "__main__":
    sys.exit(main())
