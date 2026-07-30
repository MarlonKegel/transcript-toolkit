"""What the app knows about the pipeline: steps, the commands they map to, and the prompts
and errors the CLI can answer back with.

Single source for every page: a page renders a `Step`, and every button builds its argv here.
Nothing else in `app/` may hardcode a command name or a flag — a test walks the real argparse
parser and fails if anything in this file drifts from the CLI.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..core import sampling


@dataclass(frozen=True)
class Action:
    """One button: a command with no options to decide."""
    slug: str
    title: str
    blurb: str
    argv: tuple[str, ...]
    needs_set: bool = False
    needs: tuple[str, ...] = ()     # deliverables it reads; without them the button is disabled
    explain: str = ""               # the `i` tooltip: what this is, for someone new to it
    preview: str = ""               # renders in the app as a table: "chunks" | "batches"
    aids: tuple["Action", ...] = ()  # decision aids shown beside this action, not after it


@dataclass(frozen=True)
class Review:
    """A page a step writes for you to read. `{set}` is filled in for per-set steps."""
    filename: str
    title: str


@dataclass(frozen=True)
class Step:
    """One pipeline step with a page of its own."""
    key: str                        # state.json step key (topics is per-set: "topics:<set>")
    slug: str                       # URL
    title: str
    blurb: str
    argv: tuple[str, ...]           # the run command, e.g. ("topics", "tag")
    order: int                      # pipeline position, for the dashboard
    unit: str = "interviews"        # what a run counts, in words, for "35 interviews"
    batch: bool = False             # can go to the Batch API
    per_set: bool = False           # needs --set (topics)
    needs_sample: bool = False      # its demo runs on the `toolkit sample` interviews
    deliverable: str = ""           # name in gather_status()["deliverables"]
    needs: tuple[str, ...] = ()     # deliverables that must exist first
    reviews: tuple[Review, ...] = field(default_factory=tuple)
    sequels: tuple[Action, ...] = field(default_factory=tuple)      # part of the flow
    extras: tuple[Action, ...] = field(default_factory=tuple)       # occasional, at the bottom
    review_hint: str = ""           # what to look for in the review pages, before spending


CHUNKING_EXPLAINER = (
    "An interview can be far longer than a model can read in one go, and quality drops well "
    "before that limit. So a long interview is split into overlapping pieces, and each piece "
    "is sent as its own request.\n\n"
    "The pieces overlap: each request sees the end of the previous piece for context, but "
    "only decides about its own part, so a clip boundary is never guessed at from half a "
    "conversation.\n\n"
    "Short interviews are sent whole and are not split at all. You do not have to do anything "
    "with this — it is here so you can see what will be sent before it is."
)

BATCHING_EXPLAINER = (
    "Labelling a clip works better when the model can see the clips on either side of it, so "
    "clips are sent in groups rather than one at a time — an interview's clips go out as a few "
    "requests, each carrying the clip before and after it as context.\n\n"
    "You do not have to do anything with this. It is here so you can see how the work will be "
    "divided up before anything is sent."
)

SAMPLE = Action(
    slug="sample", title="Choose demo interviews",
    blurb="Pick the handful of interviews the clip and label demos run on. Chosen once, then "
          "reused so demos stay comparable.",
    argv=("sample",),
)

# How big a demo may be is the toolkit's rule, not the app's: `toolkit sample` refuses the same
# sizes the app will not offer, so the two cannot drift.
SAMPLE_DEFAULT_N = sampling.DEFAULT_N
SAMPLE_MIN_N = sampling.MIN_N
SAMPLE_MAX_N = sampling.MAX_N


def sample_argv(n: int, interviews: list[str] | None = None) -> list[str]:
    """`toolkit sample`, with a size and optionally the interviews to include.

    Named interviews are always in the sample; if `n` is larger than the number named, the CLI
    fills the rest at random (core/sampling.py). The app never does that arithmetic itself.
    """
    argv = [*SAMPLE.argv, "--n", str(n)]
    if interviews:
        argv += ["--interviews", ",".join(interviews)]
    return argv


IMPORT = Action(
    slug="import", title="Import transcripts",
    blurb="Parse the .docx files in data/ into the paragraph dataset everything else reads.",
    argv=("import",),
)

STEPS: tuple[Step, ...] = (
    Step(
        key="clip", slug="clip", title="Clip", order=1,
        blurb="Split each interview into topically coherent clips.",
        argv=("clip",), deliverable="clips", needs_sample=True,
        reviews=(Review("index.html", "Open the review pages"),),
        review_hint="Read a few interviews through: do the clips start and end where a subject "
                    "changes, and is anything long left in one piece that should be two?",
        extras=(
            Action("annotate", "Re-render review pages",
                   "Rebuild the per-interview review pages from the saved clips (no API calls).",
                   ("clip", "annotate"), needs=("clips",)),
            Action("preview", "How interviews will be split up",
                   "See how each interview is divided before anything is sent to OpenAI.",
                   ("clip", "preview"), preview="chunks", explain=CHUNKING_EXPLAINER),
        ),
    ),
    Step(
        key="label", slug="label", title="Label", order=2,
        blurb="Write a one-line label for every clip.",
        argv=("label",), batch=True, deliverable="labels", needs=("clips",),
        needs_sample=True, reviews=(Review("index.html", "Open the review pages"),),
        review_hint="Check that a label says what the clip is about rather than judging it, and "
                    "that names and spellings are written the way your project writes them.",
        extras=(
            Action("annotate", "Re-render review pages",
                   "Rebuild the per-interview review pages from the saved labels (no API calls).",
                   ("label", "annotate"), needs=("labels",)),
            Action("preview", "How clips will be grouped",
                   "See how clips are grouped before anything is sent to OpenAI.",
                   ("label", "preview"), needs=("clips",), preview="batches",
                   explain=BATCHING_EXPLAINER),
        ),
    ),
    Step(
        key="summarize", slug="summarize", title="Summarize", order=3,
        blurb="Write a 'scope and content' abstract for each interview.",
        argv=("summarize",), batch=True, deliverable="summaries",
        reviews=(Review("demo_summaries.html", "Open the demo summaries"),
                 Review("summaries.html", "Open the summaries")),
        review_hint="Check the length and the register: an abstract should describe what the "
                    "interview covers, in your catalogue's voice, without interpreting it.",
        extras=(
            Action("annotate", "Re-render review page",
                   "Rebuild the review page from the saved summaries (no API calls).",
                   ("summarize", "annotate"), needs=("summaries",)),
        ),
    ),
    Step(
        key="topics", slug="topics", title="Topics", order=4,
        blurb="Score every clip against your own topic list, then roll the scores up to "
              "interview-level tags.",
        argv=("topics", "tag"), batch=True, per_set=True, deliverable="topics", needs=("clips",),
        unit="clips",
        reviews=(Review("{set}_demo.html", "Open the demo page"),
                 Review("{set}_index.html", "Open the review pages")),
        review_hint="Read the justifications: where a score looks wrong, the topic's description "
                    "in your topic list is usually what needs changing, not the prompt.",
        sequels=(
            Action("rollup", "Roll up to interview tags",
                   "Turn the per-clip scores into one set of tags per interview. Run this "
                   "after tagging the whole collection.",
                   ("topics", "rollup"), needs_set=True, needs=("topics:{set}",),
                   aids=(
                       Action("thresholds", "Compare thresholds first",
                              "Shows what each threshold would tag, side by side, so you can "
                              "pick one before rolling up (no API calls).",
                              ("topics", "thresholds"), needs_set=True,
                              needs=("topics:{set}",)),
                   )),
        ),
        extras=(
            Action("annotate", "Re-render review pages",
                   "Rebuild the per-interview review pages from the saved tags (no API calls).",
                   ("topics", "annotate"), needs_set=True, needs=("topics:{set}",)),
        ),
    ),
    Step(
        key="locations", slug="locations", title="Locations", order=5,
        blurb="Tag clips with the countries and regions they talk about.",
        argv=("locations", "tag"), batch=True, deliverable="locations", needs=("clips",),
        unit="clips", reviews=(Review("locations.html", "Open the review page"),),
        review_hint="Check that places the narrator only mentions in passing are not tagged as "
                    "what the clip is about, and that spellings match across interviews.",
        sequels=(
            Action("map", "Expand regions into countries",
                   "Turn each region tag into the countries it covers, and settle on one "
                   "spelling per place. Run this after tagging the whole collection.",
                   ("locations", "map"), needs=("locations",)),
            Action("rollup", "Roll up to interview places",
                   "Turn the per-clip places into one set per interview.",
                   ("locations", "rollup"), needs=("locations",),
                   aids=(
                       Action("thresholds", "Compare thresholds first",
                              "Shows what each threshold would tag, side by side, so you can "
                              "pick one before rolling up (no API calls).",
                              ("locations", "thresholds"), needs=("locations",)),
                   )),
        ),
        extras=(
            Action("annotate", "Re-render review page",
                   "Rebuild the review page from the saved tags (no API calls).",
                   ("locations", "annotate"), needs=("locations",)),
            Action("survey", "Place-name survey",
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


def missing_for(action: Action, deliverables: list[str], set_name: str | None = None) -> list[str]:
    """What this action reads that is not there yet.

    An action whose input does not exist can only fail, so the page disables the button and
    says what is missing — rather than letting someone click it and read a stack of words in
    the terminal about a step they have not run.
    """
    have = set(deliverables)
    return [need.format(set=set_name or "") for need in action.needs
            if need.format(set=set_name or "") not in have]


# Every step prints one `  [3/12] ...` line per unit as it finishes it, so how far a run has got
# is already on screen — this reads it back so the page can show it as a bar instead. The Batch
# API's own polling line (`  [   42s] status=...`) deliberately does not match.
PROGRESS_RE = re.compile(r"^\s*\[(\d+)/(\d+)\]")


def progress_of(lines) -> tuple[int, int] | None:
    """(units done, units in total) for the run, or None before the first one finishes."""
    for line in reversed(list(lines)):
        match = PROGRESS_RE.match(line)
        if match:
            done, total = int(match.group(1)), int(match.group(2))
            if 0 < total and done <= total:
                return done, total
    return None


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

# What the two ways of sending a full run mean. The figures beside the buttons are the step's
# own; this only explains what it is choosing between.
TRANSPORT_EXPLAINER = (
    "Two ways to send the same work to OpenAI.\n\n"
    "RUN NOW sends the calls straight away and they come back over the next minutes or hours, "
    "with the progress on screen. Choose this when you want the results today, or when you are "
    "still deciding and might want to stop partway.\n\n"
    "THE BATCH API hands the whole job over and OpenAI works through it when it has room. It "
    "costs half as much and can take up to a day — usually much less. The toolkit waits for it, "
    "but you can quit and re-run the same command later: it picks the same job back up rather "
    "than paying twice.\n\n"
    "Either way, nothing you have already paid for is sent again, and stopping is safe."
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


# What the CLI says when the user answers "no" at a confirmation prompt (core/console.py).
CANCELLED_MARKER = "Aborted."


def is_cancellation(error_text: str) -> bool:
    """Whether a failed run was simply declined at the prompt."""
    return error_text.strip() == CANCELLED_MARKER


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
