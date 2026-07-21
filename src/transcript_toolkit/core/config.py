"""Two-level config loading.

Root `config.yaml` holds the blessed user-facing settings, sectioned per step; `advanced/<step>.yaml`
holds every other tunable. `load_step_config` merges the two into one flat dict for the step —
root section keys win over advanced keys (the user file is authoritative).
"""
from __future__ import annotations

from pathlib import Path

import yaml

from ..errors import ToolkitError
from ..project import Project

STEP_NAMES = ("import", "clip", "label", "summarize", "topics", "locations", "export")


def read_yaml(path: Path) -> dict:
    if not path.exists():
        raise ToolkitError(f"Missing config file: {path}")
    try:
        loaded = yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        raise ToolkitError(f"Could not parse {path}: {e}") from e
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ToolkitError(f"{path} must contain a YAML mapping, got {type(loaded).__name__}")
    return loaded


def load_root_config(project: Project) -> dict:
    return read_yaml(project.config_path)


def load_step_config(project: Project, step: str) -> dict:
    if step not in STEP_NAMES:
        raise ValueError(f"Unknown step {step!r}; expected one of {STEP_NAMES}")
    root = load_root_config(project)
    section = root.get(step) or {}
    if not isinstance(section, dict):
        raise ToolkitError(f"config.yaml section {step!r} must be a mapping")
    advanced = read_yaml(project.advanced_dir / f"{step}.yaml")
    return {**advanced, **section}


def require(cfg: dict, keys: list[str], context: str) -> None:
    missing = [k for k in keys if cfg.get(k) is None]
    if missing:
        raise ToolkitError(f"Missing required setting(s) for {context}: {', '.join(missing)} "
                           f"(check config.yaml and advanced/)")


def project_name(project: Project) -> str:
    root = load_root_config(project)
    return (root.get("project") or {}).get("name") or project.root.name
