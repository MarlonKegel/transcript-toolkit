"""`toolkit status` — workspace overview: corpus, per-step demo/run state."""
from __future__ import annotations

import json

from ..core.config import project_name
from ..project import Project
from ..state import load_state


def gather_status(project: Project) -> dict:
    docx = sorted(p.relative_to(project.data_dir).as_posix()
                  for p in project.data_dir.rglob("*.docx"))
    return {
        "workspace": str(project.root),
        "name": project_name(project),
        "docx_files": len(docx),
        "imported": project.paragraphs_path.exists(),
        "steps": load_state(project)["steps"],
    }


def run_status(project: Project, as_json: bool = False) -> None:
    info = gather_status(project)
    if as_json:
        print(json.dumps(info, indent=2))
        return
    print(f"Workspace: {info['workspace']}  ({info['name']})")
    print(f"Transcripts in data/: {info['docx_files']} .docx"
          + ("" if info["imported"] else "   (not yet imported — run `toolkit import`)"))
    if not info["steps"]:
        print("No step runs recorded yet.")
        return
    print("Steps:")
    for step_key, rec in sorted(info["steps"].items()):
        demo = rec.get("demo")
        full = rec.get("full")
        demo_txt = f"demo {demo['at']}" if demo else "no demo"
        full_txt = f"full run {full['at']} ({full['model']}, {full['n_units']} units)" if full else "no full run"
        print(f"  {step_key:<16} {demo_txt:<28} {full_txt}")
