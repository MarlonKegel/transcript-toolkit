"""`toolkit status` — workspace overview: corpus, per-step demo/run state, what export includes."""
from __future__ import annotations

import json

from ..core.config import load_root_config, project_name
from ..project import Project
from ..state import load_state


def _corpus(project: Project) -> dict:
    docx = sorted(p.relative_to(project.data_dir).as_posix()
                  for p in project.data_dir.rglob("*.docx") if not p.name.startswith("~$"))
    imported = project.paragraphs_path.exists()
    stale = False
    if imported and docx:
        newest_docx = max((project.data_dir / d).stat().st_mtime for d in docx)
        stale = newest_docx > project.paragraphs_path.stat().st_mtime
    return {"docx_files": len(docx), "imported": imported, "import_stale": stale}


def _deliverables(project: Project) -> list[str]:
    out = project.outputs_dir
    present = []
    if (out / "clips" / "clips.parquet").exists():
        present.append("clips")
    if (out / "labels" / "labels.parquet").exists():
        present.append("labels")
    if (out / "summaries" / "summaries.parquet").exists():
        present.append("summaries")
    sets = ((load_root_config(project).get("topics") or {}).get("sets") or {})
    for s in sets:
        if (out / "topics" / f"{s}_clip_topics_wide.parquet").exists():
            present.append(f"topics:{s}")
    if (out / "locations" / "clip_countries.parquet").exists():
        present.append("locations")
    return present


def gather_status(project: Project) -> dict:
    return {
        "workspace": str(project.root),
        "name": project_name(project),
        **_corpus(project),
        "steps": load_state(project)["steps"],
        "deliverables": _deliverables(project),
    }


def run_status(project: Project, as_json: bool = False) -> None:
    info = gather_status(project)
    if as_json:
        print(json.dumps(info, indent=2))
        return
    print(f"Workspace: {info['workspace']}  ({info['name']})")
    imp = "" if info["imported"] else "   (not yet imported — run `toolkit import`)"
    if info.get("import_stale"):
        imp = "   (transcripts changed since import — re-run `toolkit import`)"
    print(f"Transcripts in data/: {info['docx_files']} .docx{imp}")

    if info["steps"]:
        print("\nSteps:")
        for step_key, rec in sorted(info["steps"].items()):
            demo = rec.get("demo")
            full = rec.get("full")
            demo_txt = f"demo {demo['at'][:10]}" if demo else "no demo"
            full_txt = (f"full {full['at'][:10]} ({full['model']}, {full['n_units']})"
                        if full else "no full run")
            print(f"  {step_key:<16} {demo_txt:<20} {full_txt}")

    print(f"\nExport would include: {', '.join(info['deliverables']) or '(nothing yet — run some steps)'}")
