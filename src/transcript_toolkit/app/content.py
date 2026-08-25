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
class Review:
    """A page a step writes for you to read. `{set}` is filled in for per-set steps."""
    filename: str
    title: str


@dataclass(frozen=True)
class Action:
    """One button: a command with no options to decide."""
    slug: str
    title: str
    blurb: str
    argv: tuple[str, ...]
    needs_set: bool = False
    needs: tuple[str, ...] = ()     # what it reads (see `available`); missing -> button disabled
    explain: str = ""               # the `i` tooltip: what this is, for someone new to it
    preview: str = ""               # renders in the app as a table: "chunks" | "batches"
    reviews: tuple[Review, ...] = ()   # pages it writes, linked once they are there
    options: str = ""               # extra controls the app draws for it: "compare"
    # A setting decided at this point in the flow rather than among the step's settings, because
    # the move before it is what shows you how to decide it. "rollup" is the only one: you pick
    # the rule and run it with that rule, which is one move, not two.
    setting: str = ""


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
    deliverable: str = ""           # what a full run of this step produces (see `available`)
    needs: tuple[str, ...] = ()     # what it reads; must exist before the step can run
    reviews: tuple[Review, ...] = field(default_factory=tuple)
    # The moves that follow tagging, in order. Numbered on the page, because the order is the
    # work: see what each way of deciding would tag, then roll up with the one you picked.
    sequels: tuple[Action, ...] = field(default_factory=tuple)
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

ROLLUP_EXPLAINER = (
    "The model tags clips. A catalogue entry is about a whole interview, so those clip tags have "
    "to become interview tags, and that takes a rule: what share of an interview's clips must "
    "carry a topic before the interview itself is tagged with it.\n\n"
    "The three methods differ only in how that share is set. A flat threshold asks the same "
    "share of every topic. The two binned methods sort the topics by how often they come up "
    "across the whole collection, split them into bins, and give the bins that come up less a "
    "lower share to clear — so what a topic has to reach depends on how common it is.\n\n"
    "Which to use depends on your collection and what the tags are for. This step draws what "
    "each of them would tag, worked out against your own results, so the choice is made by "
    "looking rather than by guessing at numbers."
)

# The controls the app draws beside a `thresholds` run, and the flags they become. Nothing else
# in app/ may name a flag, so the compare options are described here and nowhere else.
COMPARE_FIELDS = (
    ("bins", "--bins", "Bins to compare",
     "How many rarity bins to split the topics into. More bins means a finer ladder of "
     "thresholds."),
    ("ranges", "--ranges", "Ranges to compare",
     "The lowest and the highest threshold, per range. Write them as 10-30, comma separated."),
    ("flat", "--flat", "Flat thresholds to compare",
     "The one-threshold-for-everything percentages to draw beside the binned ones."),
)


def compare_argv(action: "Action", set_name: str | None, chosen: dict[str, str]) -> list[str]:
    """`toolkit ... thresholds` with whatever the user asked it to draw. An empty box means
    'whatever the project says', which is exactly what leaving the flag off does."""
    argv = action_argv(action, set_name)
    for key, flag, _, _ in COMPARE_FIELDS:
        said = (chosen.get(key) or "").strip()
        if said:
            argv += [flag, said]
    return argv


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
        argv=("clip",), batch=True, deliverable="clips", needs_sample=True,
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
            Action("thresholds", "Decide how to go from clip tags to interview tags",
                   "A topic becomes one of an interview's tags once enough of that interview's "
                   "clips were tagged with it — and 'enough' is your decision. This draws what "
                   "each way of deciding would tag, side by side. Nothing is sent to OpenAI.",
                   ("topics", "thresholds"), needs_set=True, needs=("topics:{set}",),
                   reviews=(Review("{set}_thresholds.html", "Open the comparison"),),
                   options="compare", explain=ROLLUP_EXPLAINER),
            Action("rollup", "Roll up to interview tags",
                   "Set the rule you settled on and apply it: the per-clip scores become one set "
                   "of tags per interview. Free and instant, so changing your mind costs a "
                   "re-run and nothing else.",
                   ("topics", "rollup"), needs_set=True, needs=("topics:{set}",),
                   setting="rollup"),
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
        unit="clips", reviews=(Review("demo.html", "Open the demo page"),
                               Review("locations.html", "Open the review page")),
        review_hint="Check that places the narrator only mentions in passing are not tagged as "
                    "what the clip is about, and that spellings match across interviews.",
        sequels=(
            Action("map", "Expand regions into countries",
                   "Turn each region tag into the countries it covers, and settle on one "
                   "spelling per place. Run this after tagging the whole collection.",
                   ("locations", "map"), needs=("locations",)),
            Action("thresholds", "Decide how to go from clip tags to interview tags",
                   "A place becomes one of an interview's places once enough of that "
                   "interview's clips talk about it — and 'enough' is your decision. This draws "
                   "what each way of deciding would tag, side by side. Nothing is sent to OpenAI.",
                   ("locations", "thresholds"), needs=("locations.map",),
                   reviews=(Review("locations_thresholds.html", "Open the comparison"),),
                   options="compare", explain=ROLLUP_EXPLAINER),
            Action("rollup", "Roll up to interview places",
                   "Set the rule you settled on and apply it: the per-clip places become one set "
                   "per interview. The same rule applies to regions, which are rolled up as "
                   "regions and only then expanded into their countries.",
                   ("locations", "rollup"), needs=("locations.map",), setting="rollup"),
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


# --- transcripts that were never SYNC'd -------------------------------------------------------
# A folder, not a separate way through the toolkit. One import reads it along with the rest, and
# every step then treats what came out of it like any other interview. The fold is on the
# Workspace page beside the transcript list, because that is what these are: transcripts.

UNSYNCED = "unsynced"
UNSYNCED_TITLE = "Transcripts that were never SYNC'd"

UNSYNCED_BLURB = (
    "A SYNC'd transcript carries a timestamp on every paragraph. Some never get one — a narrator "
    "revises the transcript so heavily that the recording no longer matches it, and the edited "
    "text becomes the record. Put those here.\n\n"
    "They are read in by the same Import, and they go through every step: they are clipped, "
    "labelled, summarized and tagged like the rest, because a clip is a run of paragraphs and "
    "paragraph numbers are something every transcript has. The one difference is that their "
    "clips have no start and end time to show, so the spreadsheet leaves those cells empty."
)


def runnable(step: Step) -> list[Action]:
    """Every button on a step's page below the demo: the sequels and the extras."""
    return [*step.sequels, *step.extras]


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


DEMO_RUN, FULL_RUN = "demo", "full run"


def job_title(step: Step, kind: str, set_name: str | None = None) -> str:
    """What a run is called while it happens, and what the status under a button matches on.

    The topic list is part of it: two lists are two pieces of work, and a panel that said only
    'Topics — demo' would be describing the wrong one half the time.
    """
    where = f" · {set_name}" if set_name and step.per_set else ""
    return f"{step.title}{where} — {kind}"


def action_title(step: Step, action: Action, set_name: str | None = None) -> str:
    return job_title(step, action.title.lower(), set_name)


def action_argv(action: Action, set_name: str | None = None) -> list[str]:
    argv = list(action.argv)
    if action.needs_set:
        if not set_name:
            raise ValueError(f"{action.slug} needs a topic set name")
        argv += ["--set", set_name]
    return argv


def missing_for(action: Action, have, set_name: str | None = None) -> list[str]:
    """What this action reads that is not there yet.

    An action whose input does not exist can only fail, so the page disables the button and
    says what is missing — rather than letting someone click it and read a stack of words in
    the terminal about a step they have not run. `have` is what `available` found on disk.
    """
    have = set(have)
    return [need.format(set=set_name or "") for need in action.needs
            if need.format(set=set_name or "") not in have]


# --- what is on disk, in the names `needs` uses -----------------------------------------------
#
# Two kinds of name, because there are two kinds of thing a button can be waiting for:
#
#   `clips`, `labels`, `summaries`, `topics:<set>`, `locations`
#       what a full run of that step writes itself;
#   `locations.map`
#       what one of the free moves that follow a step writes.
#
# Both are answered by `steps/freshness.py`, which owns the filenames — deliberately NOT by
# `toolkit status`'s deliverable list. That list answers a different question ("what would the
# spreadsheet include?"), and for locations it answers it with a file `locations map` writes,
# one command after the tagging. Gating the buttons on it made `map` wait for its own output.


def _deliverable_name(step: "Step", set_name: str | None) -> str:
    return f"{step.deliverable}:{set_name}" if step.per_set and set_name else step.deliverable


def available(project, set_name: str | None = None) -> set[str]:
    """The names in `needs` whose files are on disk right now.

    `set_name` is the topic list the page is about: a per-set step's output is only ever asked
    about one list at a time, which is the same list `missing_for` formats its needs with.
    """
    from ..steps import freshness as fresh

    have = {_deliverable_name(step, set_name) for step in STEPS
            if fresh.wrote_its_results(project, step.key, set_name)}
    have |= {f"{step_key}.{slug}" for step_key, slug in fresh.DERIVED
             if fresh.derived_exists(project, step_key, slug, set_name)}
    return have


def produces(name: str) -> tuple["Step", Action] | None:
    """The step, and the move on its page, that a `needs` name stands for.

    `None` for a step's own output, which no single button produces — the step itself does.
    """
    step_key, _, slug = name.partition(".")
    if not slug:
        return None
    step = next((s for s in STEPS if s.key == step_key), None)
    if step is None:
        return None
    action = next((a for a in runnable(step) if a.slug == slug), None)
    return (step, action) if action else None


# The moves that follow a step's own run are numbered from here on its page: try it, read it
# and then are 1, 2 and 3. Named so the page's numbering and anything that refers to a move by
# its number cannot disagree.
SEQUELS_START = 4


def sequel_number(step: "Step", action: Action) -> int | None:
    """What this move is called on the page — "4 · Expand regions into countries"."""
    return SEQUELS_START + step.sequels.index(action) if action in step.sequels else None


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


# Updating replaces the code this server is running, so the server has to start again for the
# new version to be the one in the window. It only does that when the version actually changed
# — `toolkit update` says which it was (core/update.py), and this reads it back.
UPDATE_TITLE = "Update"


def updated_version(lines) -> str | None:
    """The version an update moved to, or None if it changed nothing."""
    from ..core.update import UPDATED_MARKER

    for line in reversed(list(lines)):
        if line.strip().startswith(UPDATED_MARKER):
            return line.strip().split("->")[-1].strip() or None
    return None


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
