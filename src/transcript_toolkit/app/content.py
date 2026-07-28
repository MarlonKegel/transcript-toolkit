"""What the app knows about the pipeline: steps, the commands they map to, and the prompts
and errors the CLI can answer back with.

Single source for every page: a page renders a `Step`, and every button builds its argv here.
Nothing else in `app/` may hardcode a command name or a flag — a test walks the real argparse
parser and fails if anything in this file drifts from the CLI.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Action:
    """One button: a command with no options to decide."""
    slug: str
    title: str
    blurb: str
    argv: tuple[str, ...]
    needs_set: bool = False


@dataclass(frozen=True)
class Step:
    """One pipeline step with a page of its own."""
    key: str                        # state.json step key (topics is per-set: "topics:<set>")
    slug: str                       # URL
    title: str
    blurb: str
    argv: tuple[str, ...]           # the run command, e.g. ("topics", "tag")
    order: int                      # pipeline position, for the dashboard
    demo: bool = True               # has a --demo mode
    batch: bool = False             # can go to the Batch API
    per_set: bool = False           # needs --set (topics)
    deliverable: str = ""           # name in gather_status()["deliverables"]
    needs: tuple[str, ...] = ()     # deliverables that must exist first
    followups: tuple[Action, ...] = field(default_factory=tuple)


SAMPLE = Action(
    slug="sample", title="Draw demo sample",
    blurb="Pick the handful of interviews the clip and label demos run on. Drawn once, then "
          "reused so demos stay comparable.",
    argv=("sample",),
)

IMPORT = Action(
    slug="import", title="Import transcripts",
    blurb="Parse the .docx files in data/ into the paragraph dataset everything else reads.",
    argv=("import",),
)

STEPS: tuple[Step, ...] = (
    Step(
        key="clip", slug="clip", title="Clip", order=1,
        blurb="Split each interview into topically coherent clips.",
        argv=("clip",), deliverable="clips",
        followups=(
            Action("annotate", "Re-render review pages",
                   "Rebuild the per-interview review pages from the saved clips (no API calls).",
                   ("clip", "annotate")),
            Action("preview", "Preview chunking",
                   "Show how each interview will be split into chunks before any call is made.",
                   ("clip", "preview")),
        ),
    ),
    Step(
        key="label", slug="label", title="Label", order=2,
        blurb="Write a one-line label for every clip.",
        argv=("label",), batch=True, deliverable="labels", needs=("clips",),
        followups=(
            Action("annotate", "Re-render review pages",
                   "Rebuild the per-interview review pages from the saved labels (no API calls).",
                   ("label", "annotate")),
            Action("preview", "Preview batching",
                   "Show how clips will be grouped into calls before any call is made.",
                   ("label", "preview")),
        ),
    ),
    Step(
        key="summarize", slug="summarize", title="Summarize", order=3,
        blurb="Write a 'scope and content' abstract for each interview.",
        argv=("summarize",), batch=True, deliverable="summaries",
        followups=(
            Action("annotate", "Re-render review page",
                   "Rebuild the review page from the saved summaries (no API calls).",
                   ("summarize", "annotate")),
        ),
    ),
    Step(
        key="topics", slug="topics", title="Topics", order=4,
        blurb="Score every clip against your own topic list, then roll the scores up to "
              "interview-level tags.",
        argv=("topics", "tag"), batch=True, per_set=True, deliverable="topics", needs=("clips",),
        followups=(
            Action("rollup", "Roll up to interviews",
                   "Turn clip scores into one set of tags per interview.",
                   ("topics", "rollup"), needs_set=True),
            Action("thresholds", "Threshold decision aid",
                   "Compare rollup thresholds side by side to choose one (no API calls).",
                   ("topics", "thresholds"), needs_set=True),
            Action("annotate", "Re-render review pages",
                   "Rebuild the per-interview review pages from the saved tags (no API calls).",
                   ("topics", "annotate"), needs_set=True),
        ),
    ),
    Step(
        key="locations", slug="locations", title="Locations", order=5,
        blurb="Tag clips with the countries and regions they talk about.",
        argv=("locations", "tag"), batch=True, deliverable="locations", needs=("clips",),
        followups=(
            Action("map", "Map regions to countries",
                   "Expand region tags into countries and apply the label canon.",
                   ("locations", "map")),
            Action("rollup", "Roll up to interviews",
                   "Turn clip tags into one set of places per interview.",
                   ("locations", "rollup")),
            Action("thresholds", "Threshold decision aid",
                   "Compare rollup schemes side by side to choose one (no API calls).",
                   ("locations", "thresholds")),
            Action("annotate", "Re-render review page",
                   "Rebuild the review page from the saved tags (no API calls).",
                   ("locations", "annotate")),
            Action("survey", "Place-name survey (advanced)",
                   "Offline scan of place mentions in the transcripts. Needs the optional "
                   "[survey] install; slow.",
                   ("locations", "survey")),
        ),
    ),
)

BY_SLUG = {s.slug: s for s in STEPS}


def step_key(step: Step, set_name: str | None = None) -> str:
    """The key this run is recorded under in state.json."""
    if step.per_set:
        if not set_name:
            raise ValueError(f"{step.slug} needs a topic set name")
        return f"{step.key}:{set_name}"
    return step.key


def run_argv(step: Step, *, demo: bool, set_name: str | None = None) -> list[str]:
    """The command for a demo or a full run.

    A full run carries no `--yes` and no `--batch` on purpose: the CLI's own confirmation
    prompt is what the app shows (see jobs.py), so the cost figures the user approves are
    the CLI's own and cannot drift from it.
    """
    argv = list(step.argv)
    if step.per_set:
        if not set_name:
            raise ValueError(f"{step.slug} needs a topic set name")
        argv += ["--set", set_name]
    if demo:
        argv.append("--demo")
    return argv


def action_argv(action: Action, set_name: str | None = None) -> list[str]:
    argv = list(action.argv)
    if action.needs_set:
        if not set_name:
            raise ValueError(f"{action.slug} needs a topic set name")
        argv += ["--set", set_name]
    return argv


def display_command(argv: list[str]) -> str:
    """What the user would type in Terminal, inside their workspace. `--project` is added by
    the app (jobs.py) and left out here — showing it would make the line un-typeable."""
    return "toolkit " + " ".join(argv)


# --- reading the CLI's answers back ------------------------------------------------------
#
# The app never invents a question or a number: it shows what the CLI printed. These two
# tables are the only places that read CLI text, and both are covered by tests that compare
# them against the strings core/console.py and state.py actually produce.

CHOICE_PROMPT = "Choose [1/2/n] "          # core/console.py choose_transport (menu form)
YES_NO_SUFFIX = "[y/N] "                   # confirm_or_abort, and choose_transport's short form


@dataclass(frozen=True)
class Answer:
    """One button under a prompt the running command is waiting on."""
    label: str
    send: str
    tone: str = ""                          # quasar colour, "" = default


TRANSPORT_ANSWERS = (
    Answer("Run now", "1", "primary"),
    Answer("Use the Batch API", "2", "secondary"),
    Answer("Cancel", "n", "negative"),
)
YES_NO_ANSWERS = (
    Answer("Yes, go ahead", "y", "primary"),
    Answer("Cancel", "n", "negative"),
)


def answers_for(prompt: str) -> tuple[Answer, ...] | None:
    """Which buttons to offer for the prompt the command is blocked on, or None if the text
    isn't a prompt we recognise (then the log shows a free-text field instead)."""
    if prompt.endswith(CHOICE_PROMPT):
        return TRANSPORT_ANSWERS
    if prompt.endswith(YES_NO_SUFFIX):
        return YES_NO_ANSWERS
    return None


# Errors that mean "you skipped a step", each with the button that fixes it. The marker
# strings come from core/sampling.py and state.py; a test asserts they still match.
NO_SAMPLE_MARKER = "No demo sample drawn yet"
NO_DEMO_MARKER = "No demo run recorded for"
STALE_DEMO_MARKER = "is stale: the prompt, model, or settings have changed"


def fix_for(error_text: str) -> str | None:
    """The remedy for a failed run: 'sample', 'demo', or None (nothing mechanical to offer).

    The CLI's message is always shown as well — it is written for humans and names the fix in
    words. This only decides whether the app can also offer a button for it.
    """
    if NO_SAMPLE_MARKER in error_text:
        return "sample"
    if NO_DEMO_MARKER in error_text or STALE_DEMO_MARKER in error_text:
        return "demo"
    return None
