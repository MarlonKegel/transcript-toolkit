"""Per-call JSONL cache primitives (ported from the working repo's shared/lib/llm_utils.py).

Every expensive step keeps an append-only JSONL cache under .toolkit/cache/, one record per
LLM call, keyed by `cache_key(...)` over everything that shapes the call (model, reasoning,
verbosity, instructions, rendered input). Editing a prompt/config invalidates naturally because
the key changes; re-running a step re-uses every record whose key still matches.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from threading import Lock
from typing import Iterator


def cache_key(*parts: str) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(b"\x00")
        h.update(str(part).encode("utf-8"))
    return h.hexdigest()[:16]


def iter_jsonl(path: Path) -> Iterator[dict]:
    if not path.exists():
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def latest_records(path: Path, key_field: str = "key") -> dict[str, dict]:
    """Load a JSONL cache into {key: record}, keeping the LAST record per key (append-only
    caches may contain superseded records for a key; the newest wins)."""
    records: dict[str, dict] = {}
    for rec in iter_jsonl(path):
        records[rec[key_field]] = rec
    return records


class JsonlAppender:
    """Thread-safe append-with-fsync JSONL writer."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._lock = Lock()

    def append(self, record: dict) -> None:
        line = json.dumps(record, ensure_ascii=False)
        with self._lock:
            with open(self._path, "a") as f:
                f.write(line + "\n")
                f.flush()
                os.fsync(f.fileno())
