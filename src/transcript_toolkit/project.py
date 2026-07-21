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
    def paragraphs_path(self) -> Path: return self.data_dir / "paragraphs.parquet"

    def exists(self) -> bool:
        return self.marker_path.exists()


def find_project(explicit: str | None = None, start: Path | None = None) -> Project:
    if explicit is not None:
        project = Project(Path(explicit))
        if not project.exists():
            raise ToolkitError(f"{project.root} is not a toolkit workspace (no .toolkit/project.json). "
                               f"Create one with: toolkit init <dir>")
        return project
    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        project = Project(candidate)
        if project.exists():
            return project
    raise ToolkitError("Not inside a toolkit workspace. Run from within one, pass --project DIR, "
                       "or create one with: toolkit init <dir>")


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


def init_project(dest: str) -> Project:
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
    (project.config_path).write_bytes((scaffold / "config.yaml").read_bytes())
    _copy_tree(scaffold / "advanced", project.advanced_dir)
    _copy_tree(scaffold / "topics", project.topics_dir)
    (project.root / ".gitignore").write_bytes((scaffold / "gitignore.template").read_bytes())
    (project.root / ".env").write_bytes((scaffold / "env.template").read_bytes())
    (project.root / "AGENTS.md").write_bytes((scaffold / "AGENTS.md").read_bytes())
    (project.root / "CLAUDE.md").write_bytes((scaffold / "CLAUDE.md").read_bytes())

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


def reset_prompt(project: Project, name: str) -> Path:
    """Restore one prompt in the workspace to the pristine packaged default."""
    prompts = _defaults() / "prompts"
    src = prompts / name
    if not src.is_file():
        available = sorted(e.name for e in prompts.iterdir() if e.is_file()) if prompts.is_dir() else []
        raise ToolkitError(f"No default prompt named {name!r}. Available: {', '.join(available) or '(none)'}")
    dest = project.prompts_dir / name
    dest.write_bytes(src.read_bytes())
    return dest
