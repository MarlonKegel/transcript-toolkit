"""Workspace ("project") resolution and scaffolding.

A workspace is a directory created by `toolkit init` and identified by `.toolkit/project.json`.
Every command resolves the workspace either from `--project DIR` or by walking up from the
current directory, then reads/writes only inside it.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path

from . import __version__
from .errors import ToolkitError

MARKER = "project.json"           # inside .toolkit/


def _defaults() -> resources.abc.Traversable:
    return resources.files("transcript_toolkit") / "defaults"


class Project:
    """Paths of one workspace. Cheap value object — no I/O in the constructor."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    # --- user-facing dirs/files ---
    @property
    def config_path(self) -> Path: return self.root / "config.yaml"
    @property
    def advanced_dir(self) -> Path: return self.root / "advanced"
    @property
    def prompts_dir(self) -> Path: return self.root / "prompts"
    @property
    def topics_dir(self) -> Path: return self.root / "topics"
    @property
    def locations_dir(self) -> Path: return self.root / "locations"
    @property
    def data_dir(self) -> Path: return self.root / "data"
    @property
    def outputs_dir(self) -> Path: return self.root / "outputs"
    @property
    def diags_dir(self) -> Path: return self.root / "diags"
    @property
    def logs_dir(self) -> Path: return self.root / "logs"

    # --- internal (.toolkit/) ---
    @property
    def toolkit_dir(self) -> Path: return self.root / ".toolkit"
    @property
    def marker_path(self) -> Path: return self.toolkit_dir / MARKER
    @property
    def state_path(self) -> Path: return self.toolkit_dir / "state.json"
    @property
    def cache_dir(self) -> Path: return self.toolkit_dir / "cache"
    @property
    def demo_sample_path(self) -> Path: return self.toolkit_dir / "demo_sample.txt"
    @property
    def demo_dir(self) -> Path:
        """Where a demo run parks the tables the NEXT step's demo needs. Kept out of outputs/,
        which stays production-only, so a later step can be demoed before the corpus is run."""
        return self.toolkit_dir / "demo"

    @property
    def paragraphs_path(self) -> Path: return self.data_dir / "paragraphs.parquet"

    # Transcripts that were never SYNC'd. Kept in their own folder because they can only be
    # summarized — everything else in the toolkit needs the timestamps they do not have — and
    # because `toolkit import` must not find them among the transcripts it is meant to read.
    @property
    def unsynced_dir(self) -> Path: return self.data_dir / "unsynced"
    @property
    def unsynced_paragraphs_path(self) -> Path:
        return self.data_dir / "unsynced_paragraphs.parquet"

    def exists(self) -> bool:
        return self.marker_path.exists()


def find_project(explicit: str | None = None, start: Path | None = None) -> Project:
    if explicit is not None:
        project = Project(Path(explicit))
        if not project.root.is_dir():
            raise ToolkitError(f"There is no folder at {project.root}. If you moved or renamed "
                               f"the project, point at where it is now; if you deleted it, there "
                               f"is nothing to open.")
        if not project.exists():
            raise ToolkitError(f"{project.root} is not a toolkit project folder (it has no "
                               f".toolkit/project.json in it). Open the project folder itself, "
                               f"not the folder it sits in — or create one with: "
                               f"toolkit init <dir>")
        return project
    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        project = Project(candidate)
        if project.exists():
            return project
    raise ToolkitError("Not inside a toolkit workspace. Run from within one, pass --project DIR, "
                       "or create one with: toolkit init <dir>")


# --- the project's two names -----------------------------------------------------------------
#
# A project has a name people read ("Anderson Family Oral History") and a folder it lives in
# (`anderson-family-oral-history`). Only ever ONE of them is typed: the app asks for the name and
# derives the folder, `toolkit init <dir>` takes the folder and derives the name. Two independent
# names is how you end up with a folder called `pilot2` displayed everywhere as "My Oral History
# Project".

FOLDER_SAFE = "abcdefghijklmnopqrstuvwxyz0123456789-._"


def folder_name(name: str) -> str:
    """The folder a project called `name` lives in: lower case, spaces as dashes."""
    slug = "".join(c if c in FOLDER_SAFE else "-"
                   for c in name.strip().lower().replace(" ", "-"))
    while "--" in slug:
        slug = slug.replace("--", "-")
    slug = slug.strip("-.")
    if not slug:
        raise ToolkitError(f"{name!r} has no letters or numbers in it, so there is no folder "
                           f"name to make from it. Give the project a name you could type.")
    return slug


def display_name(folder: str) -> str:
    """The name shown for a project in a folder called `folder` — the reverse of `folder_name`,
    for workspaces made on the command line where the folder is what was typed."""
    words = [w for w in folder.replace("_", "-").split("-") if w]
    return " ".join(w[:1].upper() + w[1:] for w in words) or folder


def config_with_name(text: str, name: str) -> str:
    """config.yaml with the project's name written into it, as text.

    Edited as text, not loaded and dumped: the comments in config.yaml are the documentation of
    every setting, and a yaml round-trip deletes all of them. Only the `name:` line inside the
    `project:` block is touched, so a `name:` belonging to some other section is safe.
    """
    lines = text.splitlines()
    inside = False
    for i, line in enumerate(lines):
        if line.strip() and not line[0].isspace():          # a top-level key
            inside = line.rstrip() == "project:"
            continue
        if inside and line.lstrip().startswith("name:"):
            indent = line[:len(line) - len(line.lstrip())]
            lines[i] = f"{indent}name: {json.dumps(name)}"
            return "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    raise ToolkitError("This project's config.yaml has no `name:` under `project:`, so there is "
                       "nothing to rename. Add one, or set the name there by hand.")


def _copy_tree(src: resources.abc.Traversable, dest: Path) -> list[str]:
    """Copy a packaged resource directory's files into dest (flat per directory, recursive).
    Returns the copied filenames (relative to dest)."""
    copied: list[str] = []
    dest.mkdir(parents=True, exist_ok=True)
    for entry in src.iterdir():
        if entry.is_dir():
            copied += [f"{entry.name}/{name}" for name in _copy_tree(entry, dest / entry.name)]
        else:
            (dest / entry.name).write_bytes(entry.read_bytes())
            copied.append(entry.name)
    return copied


def init_project(dest: str, name: str | None = None) -> Project:
    """Create a workspace at `dest`. `name` is what the project is called in config.yaml and
    everywhere it is shown; without one it is derived from the folder."""
    root = Path(dest).expanduser().resolve()
    project = Project(root)
    if project.exists():
        raise ToolkitError(f"{root} is already a toolkit workspace.")
    if root.exists() and any(root.iterdir()):
        raise ToolkitError(f"{root} exists and is not empty; init needs a new or empty directory.")

    for d in (project.advanced_dir, project.prompts_dir, project.topics_dir, project.locations_dir,
              project.data_dir, project.outputs_dir, project.diags_dir, project.logs_dir,
              project.cache_dir):
        d.mkdir(parents=True, exist_ok=True)

    scaffold = _defaults() / "scaffold"
    project.config_path.write_text(config_with_name(
        (scaffold / "config.yaml").read_text(), name or display_name(root.name)))
    _copy_tree(scaffold / "advanced", project.advanced_dir)
    _copy_tree(scaffold / "topics", project.topics_dir)
    (project.root / ".gitignore").write_bytes((scaffold / "gitignore.template").read_bytes())
    (project.root / ".env").write_bytes((scaffold / "env.template").read_bytes())
    (project.root / "AGENTS.md").write_bytes((scaffold / "AGENTS.md").read_bytes())

    prompts = _defaults() / "prompts"
    if prompts.is_dir():
        _copy_tree(prompts, project.prompts_dir)
    locations = _defaults() / "locations"
    if locations.is_dir():
        _copy_tree(locations, project.locations_dir)

    project.marker_path.write_text(json.dumps({
        "schema": 1,
        "toolkit_version": __version__,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }, indent=2) + "\n")

    return project


# Prompts that moved or were renamed after workspaces were already created. Old names keep
# working so an existing workspace's `--reset-prompt` (and its own config) never breaks.
PROMPT_ALIASES = {
    "segment_interview.md": "clip_interview.md",
    "justify_topics.md": "prompt_addendums/justify_topics.md",
    "justify_locations.md": "prompt_addendums/justify_locations.md",
}


def _default_prompt_names(src=None, prefix: str = "") -> list[str]:
    """Every packaged default prompt, as workspace-relative posix paths (recursing subfolders)."""
    src = src if src is not None else _defaults() / "prompts"
    if not src.is_dir():
        return []
    names: list[str] = []
    for entry in src.iterdir():
        if entry.is_dir():
            names += _default_prompt_names(entry, f"{prefix}{entry.name}/")
        else:
            names.append(f"{prefix}{entry.name}")
    return sorted(names)


def reset_prompt(project: Project, name: str) -> Path:
    """Restore one prompt in the workspace to the pristine packaged default."""
    name = PROMPT_ALIASES.get(name, name)
    available = _default_prompt_names()
    if name not in available:
        raise ToolkitError(f"No default prompt named {name!r}. "
                           f"Available: {', '.join(available) or '(none)'}")
    src = _defaults() / "prompts"
    for part in name.split("/"):
        src = src / part
    dest = project.prompts_dir / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(src.read_bytes())
    return dest
