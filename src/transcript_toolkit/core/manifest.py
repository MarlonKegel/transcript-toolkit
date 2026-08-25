"""When each transcript was imported, and what the file looked like then.

One entry per transcript in `.toolkit/import_manifest.json`, per pile (synced / unsynced):
the file's content hash and the moment it was read in. The hash is what makes re-importing a
corrected transcript safe: an unchanged file keeps its original imported-at, a changed one gets
a new timestamp — and import uses the difference to throw away the results that were made from
the old text. Export shows the timestamps, so a spreadsheet can be checked against a corrected
transcript: exported before the correction was imported means out of date.

Projects imported before this file existed have no entries; those transcripts read as current
(the dataset is the authority) and get their entry on the next import.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from ..project import Project

SYNCED, UNSYNCED = "synced", "unsynced"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_manifest(project: Project) -> dict:
    if project.import_manifest_path.exists():
        return json.loads(project.import_manifest_path.read_text())
    return {"schema": 1, SYNCED: {}, UNSYNCED: {}}


def save_manifest(project: Project, manifest: dict) -> None:
    project.import_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    project.import_manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")


def plan_update(project: Project, pile: str, files_by_id: dict[str, Path],
                manifest: dict | None = None) -> tuple[dict, dict]:
    """What this import means for the manifest: the new pile, and which ids changed.

    Nothing is written here — the caller purges the changed ids' old results FIRST and saves
    after, so a crash between the two leaves the manifest still naming the old hashes and the
    next import redoes the purge instead of skipping it.

    One import plans both piles, so pass the manifest the previous call returned; loading it
    from disk each time would let the second pile's plan discard the first's.
    Returns (manifest_with_new_pile, {"new": [...], "changed": [...], "gone": [...]}).
    """
    manifest = load_manifest(project) if manifest is None else manifest
    old = manifest.get(pile, {})
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    entries: dict[str, dict] = {}
    new, changed = [], []
    for iid, path in files_by_id.items():
        digest = file_sha256(path)
        before = old.get(iid)
        if before and before.get("sha256") == digest:
            entries[iid] = {**before, "file": path.name}
        else:
            entries[iid] = {"file": path.name, "sha256": digest, "imported_at": now}
            (changed if before else new).append(iid)
    gone = [iid for iid in old if iid not in files_by_id]
    manifest[pile] = entries
    return manifest, {"new": new, "changed": changed, "gone": gone}


def stale_ids(project: Project, pile: str, files_by_id: dict[str, Path]) -> set[str]:
    """The ids whose file on disk is no longer the one that was imported.

    Cheap first: a file whose mtime is not newer than its imported-at cannot have changed
    since, so only newer files are actually hashed. No entry means imported before the
    manifest existed — current by assumption, until the next import records it.
    """
    entries = load_manifest(project).get(pile, {})
    stale: set[str] = set()
    for iid, path in files_by_id.items():
        entry = entries.get(iid)
        if entry is None:
            continue
        try:
            recorded = datetime.fromisoformat(entry["imported_at"]).timestamp()
        except (KeyError, ValueError):
            continue
        if path.stat().st_mtime <= recorded + 1:      # run records keep whole seconds
            continue
        if file_sha256(path) != entry.get("sha256"):
            stale.add(iid)
    return stale


def imported_at(project: Project, pile: str = SYNCED) -> dict[str, str]:
    """{interview_id: imported-at ISO timestamp} for one pile."""
    return {iid: e["imported_at"] for iid, e in load_manifest(project).get(pile, {}).items()
            if e.get("imported_at")}


def local_stamp(iso: str) -> str:
    """An imported-at as a reader's clock would say it: local time, minutes are enough."""
    return datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M")
