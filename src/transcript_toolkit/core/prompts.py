"""Which prompt file each step reads, and reading it.

A workspace owns its prompts: `toolkit init` copies the packaged defaults into `prompts/`, every
step reads only from there, and `toolkit init --reset-prompt NAME` puts one back. Which file a
step reads is the `prompt` key in `advanced/<step>.yaml`, except that a topic list may name its
own rubric — so this is the only place that answers "which file is this step's prompt?", and the
app asks it rather than knowing any filenames.
"""
from __future__ import annotations

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


def addendums(project: Project) -> list[str]:
    """The extra instruction files a project can append to a prompt, prompts/-relative."""
    folder = project.prompts_dir / ADDENDUM_DIR
    if not folder.is_dir():
        return []
    return sorted(f"{ADDENDUM_DIR}/{p.name}" for p in folder.iterdir() if p.is_file())
