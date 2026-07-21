"""Workspace state: demo gate + run records (.toolkit/state.json).

Demo-first is enforced here. Each step (per topic set for topics, e.g. "topics:main") records:
- demo: fingerprint + timestamp + units + the review artifact path, written only after the
  annotated review file exists;
- full: fingerprint + timestamp + model + unit count of the last deliverable-writing run.

The fingerprint is `cache_key(...)` over everything that shapes the step's LLM calls (model,
reasoning, instructions text, call-shaping advanced settings) — the same mechanism that keys
the per-call cache, so any prompt/config/taxonomy edit makes the recorded demo stale.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .errors import ToolkitError
from .project import Project


def load_state(project: Project) -> dict:
    if project.state_path.exists():
        return json.loads(project.state_path.read_text())
    return {"schema": 1, "steps": {}}


def save_state(project: Project, state: dict) -> None:
    project.state_path.parent.mkdir(parents=True, exist_ok=True)
    project.state_path.write_text(json.dumps(state, indent=2) + "\n")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _step(state: dict, step_key: str) -> dict:
    return state["steps"].setdefault(step_key, {})


def record_demo(project: Project, step_key: str, fingerprint: str,
                units: list[str], diag: str) -> None:
    state = load_state(project)
    _step(state, step_key)["demo"] = {
        "fingerprint": fingerprint, "at": _now(), "units": units, "diag": diag,
    }
    save_state(project, state)


def record_full(project: Project, step_key: str, fingerprint: str,
                model: str, n_units: int) -> None:
    state = load_state(project)
    _step(state, step_key)["full"] = {
        "fingerprint": fingerprint, "at": _now(), "model": model, "n_units": n_units,
    }
    save_state(project, state)


def demo_status(project: Project, step_key: str, fingerprint: str) -> str:
    """'none' | 'stale' | 'current' for the recorded demo vs the current fingerprint."""
    demo = load_state(project)["steps"].get(step_key, {}).get("demo")
    if demo is None:
        return "none"
    return "current" if demo["fingerprint"] == fingerprint else "stale"


def check_demo_gate(project: Project, step_key: str, fingerprint: str,
                    demo_command: str, skip: bool = False) -> None:
    """Refuse a deliverable-writing run unless a demo with the CURRENT fingerprint was reviewed.
    `demo_command` is the exact command to print in the refusal (e.g. "toolkit clip --demo")."""
    if skip:
        return
    status = demo_status(project, step_key, fingerprint)
    if status == "current":
        return
    if status == "none":
        raise ToolkitError(
            f"No demo run recorded for '{step_key}'.\n"
            f"Run `{demo_command}`, review the annotated output in diags/, adjust config/prompts "
            f"if needed, then re-run this command.")
    demo = load_state(project)["steps"][step_key]["demo"]
    raise ToolkitError(
        f"The demo for '{step_key}' (run {demo['at']}) is stale: the prompt, model, or settings "
        f"have changed since.\n"
        f"Run `{demo_command}` again, review the annotated output in diags/, then re-run this command.")
