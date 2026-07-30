"""Which prompt file each step reads, and reading it.

A workspace owns its prompts: `toolkit init` copies the packaged defaults into `prompts/`, every
step reads only from there, and `toolkit init --reset-prompt NAME` puts one back. Which file a
step reads is the `prompt` key in `advanced/<step>.yaml`, except that a topic list may name its
own rubric — so this is the only place that answers "which file is this step's prompt?", and the
app asks it rather than knowing any filenames.

Two path conventions meet here, and they are not the same:
- a **prompt name** is relative to `prompts/` (`clip_interview.md`) — that is what the `prompt`
  and `justify_prompt` settings hold, and what `load_prompt` takes;
- an **addendum path** is relative to the workspace (`prompts/prompt_addendums/house.md`) —
  that is what `label.addendum` holds, because `steps/label` resolves it from the project root.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..errors import ToolkitError
from ..project import Project

# The steps that send instructions to a model. Import and export send nothing.
PROMPTED_STEPS = ("clip", "label", "summarize", "topics", "locations")

ADDENDUM_DIR = "prompt_addendums"


def load_prompt(project: Project, name: str) -> str:
    path = project.prompts_dir / name
    if not path.exists():
        raise ToolkitError(f"Prompt not found: {path}. Restore the default with "
                           f"`toolkit init --reset-prompt {name}`.")
    return path.read_text().strip()


def prompt_name(project: Project, step: str, set_name: str | None = None) -> str:
    """The prompt `step` reads, as a path relative to the workspace's prompts/ folder."""
    from .config import load_root_config, load_step_config

    if step not in PROMPTED_STEPS:
        raise ValueError(f"{step!r} does not use a prompt")
    if step == "topics" and set_name:
        sets = ((load_root_config(project).get("topics") or {}).get("sets") or {})
        own = (sets.get(set_name) or {}).get("prompt")
        if own:
            return own
    return load_step_config(project, step)["prompt"]


def prompt_path(project: Project, step: str, set_name: str | None = None) -> Path:
    return project.prompts_dir / prompt_name(project, step, set_name)


def prompt_files(project: Project) -> dict[str, str]:
    """Every step's prompt file, for `toolkit status` — the answer to "which file do I edit?"."""
    return {step: prompt_name(project, step) for step in PROMPTED_STEPS}


def justify_prompt_names(project: Project) -> set[str]:
    """The justification instructions the toolkit switches on itself, prompts/-relative.

    A step appends these for a demo and leaves them off for a full run, and they change the shape
    of the reply it asks for. They are therefore not something to attach to a step by hand.
    """
    from .config import load_step_config

    names = set()
    for step in PROMPTED_STEPS:
        name = load_step_config(project, step).get("justify_prompt")
        if name:
            names.add(name)
    return names


def addendums(project: Project) -> list[str]:
    """The extra instruction files a project can attach to a step, workspace-relative.

    The toolkit's own justification instructions are left out: a step turns those on for its demo
    and off for a full run by itself, so attaching one by hand would only break the reply it
    expects.
    """
    folder = project.prompts_dir / ADDENDUM_DIR
    if not folder.is_dir():
        return []
    skip = justify_prompt_names(project)
    return sorted(f"prompts/{ADDENDUM_DIR}/{p.name}" for p in folder.iterdir()
                  if p.is_file() and f"{ADDENDUM_DIR}/{p.name}" not in skip)


def addendum_slug(title: str) -> str:
    """A filename from what somebody typed. It becomes a file in the project, so it has to
    survive being one."""
    cleaned = re.sub(r"[^a-z0-9]+", "_", title.strip().lower()).strip("_")
    if not cleaned:
        raise ToolkitError(f"{title!r} cannot be a file name. Use letters and numbers — for "
                           f"example: house style, spelling rules.")
    return cleaned


def write_addendum(project: Project, title: str, text: str) -> str:
    """Save extra instructions as a file in the project and return its workspace-relative path."""
    name = f"{addendum_slug(title)}.md"
    if f"{ADDENDUM_DIR}/{name}" in justify_prompt_names(project):
        raise ToolkitError(f"{name} is one of the toolkit's own files. Give yours another name.")
    folder = project.prompts_dir / ADDENDUM_DIR
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(text.strip() + "\n")
    return f"prompts/{ADDENDUM_DIR}/{name}"
