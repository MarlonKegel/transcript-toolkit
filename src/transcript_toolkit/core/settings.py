"""The settings in config.yaml: what each one is, and how to change one from the app.

The comments in config.yaml are the documentation of every setting, written for whoever opens
the file. `explanations()` reads them back out, so the app shows each setting with those same
words: change a comment in the file and the app's explanation changes with it. There is one
description of a setting, in one place, and it is the file itself.

That is also why `save()` edits the file as text. Loading config.yaml into Python and dumping
it back would produce a file with the same settings and not one comment left in it.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass

import yaml

from ..errors import ToolkitError
from ..project import Project
from .llm import REASONING_LEVELS

# What a setting is edited with. The app maps these to controls; nothing else here cares.
TEXT, MODEL, CHOICE, TOGGLE = "text", "model", "choice", "toggle"
WORDS, NUMBERS, PAIRS = "words", "numbers", "pairs"
PROMPT_FILE, ROLLUP = "prompt_file", "rollup"


@dataclass(frozen=True)
class Field:
    """One setting: where it lives in config.yaml, what to call it, and how it is edited."""
    path: str                       # dotted, e.g. "clip.model"
    label: str
    kind: str
    step: str                       # "project", or the step whose page it belongs on
    choices: tuple[str, ...] = ()
    fallback: str = ""              # what this setting falls back to when it is not set here


PROJECT = "project"

FIELDS: tuple[Field, ...] = (
    Field("project.name", "Project name", TEXT, PROJECT),

    # Import has no page of its own: it happens on the workspace page, so its settings do too.
    Field("import.interviewer_labels", "Interviewer labels", WORDS, "import"),
    Field("import.other_labels", "Other non-narrator labels", WORDS, "import"),
    Field("import.strip_suffixes", "Filename endings to ignore", WORDS, "import"),

    Field("clip.model", "Model", MODEL, "clip"),
    Field("clip.reasoning", "Thinking effort", CHOICE, "clip", REASONING_LEVELS),

    Field("label.model", "Model", MODEL, "label"),
    Field("label.reasoning", "Thinking effort", CHOICE, "label", REASONING_LEVELS),
    Field("label.addendum", "House rules added to the prompt", PROMPT_FILE, "label"),

    Field("summarize.model", "Model", MODEL, "summarize"),
    Field("summarize.reasoning", "Thinking effort", CHOICE, "summarize", REASONING_LEVELS),
    Field("summarize.pool_sessions", "One summary per narrator", TOGGLE, "summarize"),

    Field("topics.model", "Model", MODEL, "topics"),
    Field("topics.reasoning", "Thinking effort", CHOICE, "topics", REASONING_LEVELS),

    Field("locations.model", "Model", MODEL, "locations"),
    Field("locations.reasoning", "Thinking effort", CHOICE, "locations", REASONING_LEVELS),
    Field("locations.rollup.thresholds", "Region rollup bars", NUMBERS, "locations"),
    Field("locations.relabel", "Spellings to standardise", PAIRS, "locations"),
    Field("locations.place_tags", "Places tagged in their own right", WORDS, "locations"),

    Field("export.locations", "How places appear in the spreadsheet", CHOICE, "export"),
)

BY_PATH = {f.path: f for f in FIELDS}


def for_step(step: str) -> list[Field]:
    return [f for f in FIELDS if f.step == step]


def set_fields(set_name: str) -> list[Field]:
    """The settings of one topic list.

    A topic list is its own piece of work — a fine-grained list may want a stronger model than a
    coarse one — so each has its own settings rather than sharing the step's. Until one is saved
    the list runs on `topics.model` / `topics.reasoning`, which is what `fallback` shows.
    """
    base = f"topics.sets.{set_name}"
    return [
        Field(f"{base}.model", "Model", MODEL, "topics", fallback="topics.model"),
        Field(f"{base}.reasoning", "Thinking effort", CHOICE, "topics", REASONING_LEVELS,
              fallback="topics.reasoning"),
        Field(f"{base}.rollup", "How clip topics become interview topics", ROLLUP, "topics"),
    ]


def choices_for(field: Field) -> tuple[str, ...]:
    """The values a choice offers. Models come from the toolkit's price list, so a run can always
    be costed; the export modes come from the exporter itself."""
    if field.kind == MODEL:
        from .cost import pricing
        return tuple(pricing())
    if field.path == "export.locations":
        from ..steps.export import LOCATION_MODES
        return tuple(LOCATION_MODES)
    return field.choices


# --- reading -------------------------------------------------------------------------------

KEY_RE = re.compile(r"^(?P<indent> *)(?P<key>[^\s#:][^:]*):(?P<rest>.*)$")


def _split_comment(rest: str) -> tuple[str, str]:
    """A value and the trailing `# ...` after it, if any. Quoted `#` is part of the value."""
    quote = ""
    for i, ch in enumerate(rest):
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "#":
            return rest[:i], rest[i:]
    return rest, ""


RULE = set("-= ")


def _prose(comment_lines: list[str]) -> str:
    """Comment lines as something readable: the `#` gone, and the rules a section banner is
    drawn with gone too."""
    out = []
    for line in comment_lines:
        body = line.strip().lstrip("#").strip()
        if not body or set(body) <= RULE:
            continue
        out.append(body.strip("-= ").strip())
    return "\n".join(out)


def explanations(text: str) -> dict[str, str]:
    """{setting path: what the file says about it}.

    A setting is documented by the comment lines directly above it and by any comment on its own
    line. A blank line ends a comment block, which is what keeps the banner at the top of the
    file from being read as a description of the first setting under it.
    """
    found: dict[str, str] = {}
    stack: list[tuple[int, str]] = []
    block: list[str] = []
    for raw in text.split("\n"):
        stripped = raw.strip()
        if not stripped:
            block = []
            continue
        if stripped.startswith("#"):
            block.append(raw)
            continue
        match = KEY_RE.match(raw)
        if match is None:
            block = []
            continue
        indent = len(match.group("indent"))
        while stack and stack[-1][0] >= indent:
            stack.pop()
        stack.append((indent, match.group("key").strip()))
        parts = [_prose(block), _prose([_split_comment(match.group("rest"))[1]])]
        said = "\n".join(p for p in parts if p)
        if said:
            found[".".join(k for _, k in stack)] = said
        block = []
    return found


def shipped_explanations() -> dict[str, str]:
    """What the toolkit's own config.yaml says about each setting — the wording a project gets
    when `toolkit init` copies that file."""
    from ..project import _defaults
    return explanations((_defaults() / "scaffold" / "config.yaml").read_text())


def explained(said: dict[str, str], field: Field) -> str:
    """What to show beside a setting: its own comment, or the one belonging to what it falls
    back to — a per-topic-list model is the same setting as the step's, in a narrower place."""
    return said.get(field.path) or (said.get(field.fallback, "") if field.fallback else "")


def explanations_for(project: Project) -> dict[str, str]:
    """What to show beside each setting: this project's own comments, and the shipped wording for
    any setting whose comment its file does not have.

    A project created by an earlier toolkit has no comment above `model` or `reasoning`, because
    those were added later. The shipped file is the same file, so its words are the right ones to
    fall back to — and a comment the project has reworded still wins.
    """
    return {**shipped_explanations(), **explanations(project.config_path.read_text())}


def value_at(data: dict, path: str, default=None):
    cursor = data
    for key in path.split("."):
        if not isinstance(cursor, dict) or key not in cursor:
            return default
        cursor = cursor[key]
    return cursor


# --- writing -------------------------------------------------------------------------------

def dump(value) -> str:
    """One YAML value on one line, quoted where YAML needs it to be."""
    text = yaml.safe_dump({"_": value}, default_flow_style=True, allow_unicode=True,
                          sort_keys=False, width=10 ** 6).strip()
    if not (text.startswith("{_: ") and text.endswith("}")):
        raise ToolkitError(f"{value!r} cannot be written into config.yaml as one line.")
    return text[len("{_: "):-1]


def _find(lines: list[str], lo: int, hi: int, key: str, indent: int) -> int | None:
    pattern = re.compile(rf"^ {{{indent}}}{re.escape(key)}:(?:\s|$)")
    return next((i for i in range(lo, hi) if pattern.match(lines[i])), None)


def _block_end(lines: list[str], at: int, indent: int) -> int:
    """Just past what the key opened at `at` owns: everything indented deeper than it."""
    for i in range(at + 1, len(lines)):
        line = lines[i]
        if line.strip() and len(line) - len(line.lstrip(" ")) <= indent:
            return i
    return len(lines)


def _replace(lines: list[str], at: int, indent: int, value) -> list[str]:
    head, rest = lines[at].split(":", 1)
    old_value, comment = _split_comment(rest)
    new = f"{head}: {dump(value)}"
    if comment.strip():
        column = len(head) + 1 + len(old_value)
        new += " " * max(1, column - len(new)) + comment.strip()
    end = _block_end(lines, at, indent)
    while end > at + 1 and not lines[end - 1].strip():       # leave the spacing as it was
        end -= 1
    return lines[:at] + [new] + lines[end:]


def _new_block(keys: list[str], value, indent: int) -> list[str]:
    if len(keys) == 1:
        return [f"{' ' * indent}{keys[0]}: {dump(value)}"]
    return [f"{' ' * indent}{keys[0]}:", *_new_block(keys[1:], value, indent + 2)]


def _insert(lines: list[str], lo: int, hi: int, keys: list[str], value, indent: int) -> list[str]:
    while hi > lo and not lines[hi - 1].strip():
        hi -= 1
    return lines[:hi] + _new_block(keys, value, indent) + lines[hi:]


def set_value(text: str, path: str, value) -> str:
    """config.yaml with one setting changed and everything else, comments included, as it was."""
    lines = text.split("\n")
    keys = path.split(".")
    lo, hi = 0, len(lines)
    for depth, key in enumerate(keys):
        indent = depth * 2
        at = _find(lines, lo, hi, key, indent)
        if at is None:
            return "\n".join(_insert(lines, lo, hi, keys[depth:], value, indent))
        if depth == len(keys) - 1:
            return "\n".join(_replace(lines, at, indent, value))
        lo, hi = at + 1, _block_end(lines, at, indent)
    raise ToolkitError(f"Nothing to change for {path}.")


def _with(data: dict, keys: list[str], value) -> dict:
    out = copy.deepcopy(data)
    cursor = out
    for key in keys[:-1]:
        if not isinstance(cursor.get(key), dict):
            cursor[key] = {}
        cursor = cursor[key]
    cursor[keys[-1]] = value
    return out


def save(project: Project, changes: dict[str, object]) -> None:
    """Write settings into config.yaml, or change nothing and say so.

    The file is edited as text and then read back: if the result is not the old settings plus
    exactly these changes, it is thrown away rather than written. Somebody who has rearranged
    their config.yaml by hand keeps their file and is told to make the change there.
    """
    if not changes:
        return
    path = project.config_path
    text = path.read_text()
    try:
        before = yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        raise ToolkitError(f"config.yaml cannot be read, so nothing was saved: {e}") from e

    refusal = ToolkitError(
        f"{', '.join(changes)} could not be changed automatically, so nothing was saved — this "
        f"config.yaml is not laid out the way the app writes it.\n"
        f"Change them in the file itself: {path}")

    new_text, expected = text, before
    for setting, value in changes.items():
        new_text = set_value(new_text, setting, value)
        expected = _with(expected, setting.split("."), value)
    try:
        after = yaml.safe_load(new_text) or {}
    except yaml.YAMLError as e:
        raise refusal from e
    if after != expected:
        raise refusal
    path.write_text(new_text)
