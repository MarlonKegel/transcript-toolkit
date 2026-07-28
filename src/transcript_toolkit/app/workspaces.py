"""Finding, creating and remembering workspaces.

The app keeps a short list of the workspaces it has opened so the user does not have to type
a path twice. The list is a convenience only — the workspace itself is the folder on disk, and
`toolkit init` on the command line stays unaware of this file, so nothing about the CLI depends
on the app having run.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from ..core.config import project_name
from ..errors import ToolkitError
from ..project import Project, find_project, init_project

ENV_KEY = "OPENAI_API_KEY"
MAX_REMEMBERED = 12


def support_dir() -> Path:
    """Where machine-level app state lives: the Mac's conventional place, since that is the
    platform the app ships for; a Linux dev box gets the XDG equivalent."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "transcript-toolkit"
    import os
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "transcript-toolkit"


def registry_path() -> Path:
    return support_dir() / "workspaces.json"


def load_registry() -> list[dict]:
    """Remembered workspaces, most recently opened first. Entries are not checked here —
    a folder that has since been renamed or deleted stays in the list until the user removes
    it, so the app can say what happened instead of quietly forgetting their project."""
    path = registry_path()
    if not path.exists():
        return []
    try:
        entries = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise ToolkitError(f"The list of recent workspaces is unreadable: {path} ({e}). "
                           f"Delete that file to start a fresh list.") from e
    return [e for e in entries if isinstance(e, dict) and e.get("path")]


def _save(entries: list[dict]) -> None:
    path = registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries[:MAX_REMEMBERED], indent=2) + "\n")


def remember(project: Project) -> None:
    root = str(project.root)
    entries = [e for e in load_registry() if e["path"] != root]
    entries.insert(0, {"path": root, "name": project_name(project),
                       "opened": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    _save(entries)


def forget(path: str) -> None:
    _save([e for e in load_registry() if e["path"] != str(path)])


def open_workspace(path: str | Path) -> Project:
    """Open a folder as a workspace and remember it. Raises with the CLI's own wording when
    the folder is not one."""
    project = find_project(str(Path(path).expanduser()))
    remember(project)
    return project


def create_workspace(parent: str | Path, name: str) -> Project:
    """Make a new workspace called `name` inside `parent`."""
    name = name.strip()
    if not name:
        raise ToolkitError("Give the project a name.")
    if "/" in name or name.startswith("."):
        raise ToolkitError(f"{name!r} cannot be a folder name — leave out '/' and don't start "
                           f"with a dot.")
    parent_dir = Path(parent).expanduser()
    if not parent_dir.is_dir():
        raise ToolkitError(f"There is no folder at {parent_dir}. Pick one that exists.")
    project = init_project(str(parent_dir / name))
    remember(project)
    return project


def suggested_parent() -> Path:
    """Where new workspaces are offered by default: Documents, because that is where people
    keep their work and expect to find it in Finder."""
    documents = Path.home() / "Documents"
    return documents if documents.is_dir() else Path.home()


# --- the API key ---------------------------------------------------------------------------

def env_path(project: Project) -> Path:
    return project.root / ".env"


def has_api_key(project: Project) -> bool:
    """Whether a key is set. The key itself is never read into the app or shown anywhere."""
    path = env_path(project)
    if not path.exists():
        return False
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{ENV_KEY}=") and stripped[len(ENV_KEY) + 1:].strip():
            return True
    return False


def set_api_key(project: Project, key: str) -> None:
    """Write the key into the workspace's .env, replacing any earlier one and leaving the rest
    of the file (comments included) as it was."""
    key = key.strip()
    if not key:
        raise ToolkitError("Paste the key first.")
    if any(c.isspace() for c in key):
        raise ToolkitError("That key contains a space or a line break — copy it again, it "
                           "should be one unbroken string.")
    path = env_path(project)
    lines = path.read_text().splitlines() if path.exists() else []
    out, replaced = [], False
    for line in lines:
        if line.strip().startswith(f"{ENV_KEY}="):
            if not replaced:
                out.append(f"{ENV_KEY}={key}")
                replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(f"{ENV_KEY}={key}")
    path.write_text("\n".join(out) + "\n")
    path.chmod(0o600)          # a billable credential: readable by its owner and nobody else


# --- transcripts ---------------------------------------------------------------------------

def add_transcript(project: Project, filename: str, data: bytes) -> Path:
    """Put an uploaded .docx into the workspace's data/ folder, where import looks for it."""
    name = Path(filename).name
    if not name.lower().endswith(".docx"):
        raise ToolkitError(f"{name} is not a .docx file. Transcripts must be Word documents.")
    project.data_dir.mkdir(parents=True, exist_ok=True)
    dest = project.data_dir / name
    if dest.exists():
        raise ToolkitError(f"{name} is already in this project. Remove or rename the old one "
                           f"first — replacing a transcript silently would be worse.")
    dest.write_bytes(data)
    return dest


def transcript_count(project: Project) -> int:
    return sum(1 for p in project.data_dir.rglob("*.docx") if not p.name.startswith("~$"))
