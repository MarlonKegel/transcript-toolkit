"""Topic sets loaded from user spreadsheets (config: topics.sets.<set>.file).

The research repo kept each taxonomy as hand-edited markdown plus a config-listed id/name
table; the product replaces both with ONE spreadsheet per set — columns `name` (required),
`description` (required), `id` (optional; else slugified from the name). The loader
deterministically generates everything the tagger needs: the taxonomy text fed to the model,
the ordered [{id, name}] list, and (via `build_legend`) the topic-id legend.

BYTE-STABILITY WARNING: the generated taxonomy text and legend feed cache keys and demo
fingerprints. Any cosmetic change to the generated format invalidates users' caches and
recorded demos.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

from ...errors import ToolkitError
from ...project import Project

ID_RE = re.compile(r"^[a-z0-9_]+$")


@dataclass(frozen=True)
class TopicSet:
    name: str                # the set's config name, e.g. "main" — prefixes outputs and state
    ids: list[str]
    topics: list[dict]       # ordered [{id, name}], spreadsheet row order
    taxonomy_text: str       # deterministic markdown fed to the model (feeds cache keys)
    source: Path


def resolve_set(cfg: dict, set_name: str | None) -> tuple[str, dict]:
    """Resolve --set / topics.default_set to (set_name, its config entry)."""
    sets = cfg.get("sets") or {}
    if not isinstance(sets, dict) or not sets:
        raise ToolkitError("No topic sets configured. Add topics.sets.<name>.file to config.yaml.")
    name = set_name or cfg.get("default_set")
    if name is None:
        raise ToolkitError(f"No topic set given and no topics.default_set configured. "
                           f"Configured sets: {', '.join(sorted(sets))}")
    if name not in sets:
        raise ToolkitError(f"Unknown topic set {name!r}. Configured sets: {', '.join(sorted(sets))}")
    entry = sets[name]
    if not isinstance(entry, dict):
        raise ToolkitError(f"config.yaml topics.sets.{name} must be a mapping")
    return name, entry


def slug(name: str) -> str:
    """Topic id from a display name: lowercase, runs of non-alphanumerics -> _."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _read_table(path: Path) -> list[list[str]]:
    """Raw rows (header first) from a .csv or .xlsx — every cell stringified, deterministic."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with open(path, newline="", encoding="utf-8-sig") as f:
            return [["" if c is None else str(c) for c in row] for row in csv.reader(f)]
    if suffix == ".xlsx":
        from openpyxl import load_workbook
        wb = load_workbook(path, read_only=True, data_only=True)
        try:
            return [["" if c is None else str(c) for c in row]
                    for row in wb.worksheets[0].iter_rows(values_only=True)]
        finally:
            wb.close()
    raise ToolkitError(f"Topic set file must be .csv or .xlsx, got: {path.name}")


def load_topic_set(project: Project, cfg: dict, set_name: str | None = None) -> TopicSet:
    """Load one topic set's spreadsheet into a TopicSet. `cfg` is the merged topics step
    config (load_step_config(project, "topics")); the `sets` dict arrives nested in it."""
    name, entry = resolve_set(cfg, set_name)
    file_rel = entry.get("file")
    if not file_rel:
        raise ToolkitError(f"config.yaml topics.sets.{name} has no `file` "
                           f"(path to the topic spreadsheet, relative to the workspace).")
    path = project.root / file_rel
    if not path.exists():
        raise ToolkitError(f"Topic set file not found: {path}")

    raw = _read_table(path)
    if not raw:
        raise ToolkitError(f"{path.name} is empty")
    header = [h.strip().lower() for h in raw[0]]
    for col in ("name", "description"):
        if col not in header:
            raise ToolkitError(f"{path.name} needs a {col!r} column "
                               f"(found: {', '.join(h for h in header if h) or '(none)'})")

    topics: list[dict] = []
    blocks: list[str] = []
    seen: dict[str, int] = {}          # id -> row number, for duplicate reporting
    for rownum, cells in enumerate(raw[1:], start=2):
        row = dict(zip(header, cells))
        if not any(v.strip() for v in row.values()):
            continue                   # blank row (common in xlsx exports)
        topic_name = (row.get("name") or "").strip()
        description = (row.get("description") or "").strip()
        if not topic_name:
            raise ToolkitError(f"{path.name} row {rownum}: empty topic name")
        if not description:
            raise ToolkitError(f"{path.name} row {rownum}: empty description for topic {topic_name!r}")
        tid = (row.get("id") or "").strip() or slug(topic_name)
        if not ID_RE.match(tid):
            raise ToolkitError(f"{path.name} row {rownum}: invalid topic id {tid!r} "
                               f"(must match ^[a-z0-9_]+$; give an explicit `id` column value)")
        if tid in seen:
            raise ToolkitError(f"{path.name} row {rownum}: duplicate topic id {tid!r} "
                               f"(also produced by row {seen[tid]})")
        seen[tid] = rownum
        topics.append({"id": tid, "name": topic_name})
        blocks.append(f"## {topic_name}\n\n{description}")
    if not topics:
        raise ToolkitError(f"{path.name} has no topic rows")

    return TopicSet(name=name, ids=[t["id"] for t in topics], topics=topics,
                    taxonomy_text="\n\n".join(blocks), source=path)


def build_legend(topics: list[dict]) -> str:
    """The id<->name legend prepended to the taxonomy so the model knows which id to use.
    Ported byte-identical from the working repo's tag-topics utils."""
    lines = ["## Topics", "",
             "Score the clip against each of these topics, using exactly these ids in your output. "
             "Definitions follow below.", ""]
    lines += [f"- `{t['id']}` — {t['name']}" for t in topics]
    return "\n".join(lines)
