"""OpenAI Batch API transport (50%-off async tier), generalized from the working repo's
tag-locations batch script.

`run_batch` takes a list of request units and drives the whole cycle: build requests.jsonl ->
files.create -> batches.create -> poll -> download -> parse. Artifacts live under a caller-supplied
directory, keyed by a fingerprint of the request set:

    requests_{fp}.jsonl / batch_{fp}.json / results_raw_{fp}.jsonl

Idempotent + resumable: re-running with the same pending set attaches to the in-flight batch
(persisted batch_{fp}.json) instead of resubmitting; a changed set gets a new fingerprint and thus
a new batch. Failed requests are returned as failures, never silently dropped — the caller decides
what stays uncached (so the next run batches exactly the missing units).
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from ..errors import ToolkitError

ENDPOINT = "/v1/responses"
RUNNING = ("validating", "in_progress", "finalizing")
COLLECTABLE = ("completed", "expired")   # 'expired' carries the completed-in-window subset


def build_request_line(unit: dict) -> str:
    """One Batch-API request line for a unit of
    {custom_id, instructions, user_content, schema, model, reasoning, verbosity, prompt_cache_key}."""
    return json.dumps({
        "custom_id": unit["custom_id"], "method": "POST", "url": ENDPOINT,
        "body": {"model": unit["model"], "instructions": unit["instructions"],
                 "input": unit["user_content"],
                 "reasoning": {"effort": unit["reasoning"]},
                 "text": {"verbosity": unit["verbosity"], "format": unit["schema"]},
                 "prompt_cache_key": unit["prompt_cache_key"]},
    })


def output_text_from_body(body: dict) -> str:
    for item in body.get("output", []):
        if item.get("type") == "message":
            for c in item.get("content", []):
                if c.get("type") == "output_text":
                    return c["text"]
        if item.get("type") == "refusal":
            raise RuntimeError(f"Model refused: {item.get('refusal')}")
    raise RuntimeError(f"No output_text in body: {json.dumps(body)[:400]}")


def usage_from_body(body: dict) -> dict:
    """Map the raw response-body usage into the standard cache-record usage shape."""
    u = body.get("usage") or {}
    return {
        "input_tokens": u.get("input_tokens"),
        "output_tokens": u.get("output_tokens"),
        "reasoning_tokens": (u.get("output_tokens_details") or {}).get("reasoning_tokens"),
        "cached_input_tokens": (u.get("input_tokens_details") or {}).get("cached_tokens"),
    }


def _poll(client, batch_id: str, poll_interval_s: float, max_total_wait_s: float):
    b = client.batches.retrieve(batch_id)
    t0 = time.monotonic()
    while b.status in RUNNING:
        rc = b.request_counts
        print(f"  [{int(time.monotonic() - t0):>5}s] status={b.status:11} "
              f"completed={getattr(rc, 'completed', 0)}/{getattr(rc, 'total', 0)} "
              f"failed={getattr(rc, 'failed', 0)}", flush=True)
        if time.monotonic() - t0 > max_total_wait_s:
            return b
        time.sleep(poll_interval_s)
        b = client.batches.retrieve(batch_id)
    return b


def run_batch(client, units: list[dict], batch_dir: Path, poll_interval_s: float = 20.0,
              max_total_wait_s: float = 86400.0, metadata: dict | None = None,
              ) -> tuple[dict[str, tuple[dict, dict]], list[tuple[str, str]]]:
    """Run (or resume) one batch over `units`. Returns (results, failures):
    results = {custom_id: (parsed_json, usage)}; failures = [(custom_id, error_text), ...]."""
    if not units:
        return {}, []
    lines = [build_request_line(u) for u in sorted(units, key=lambda u: u["custom_id"])]
    fp = hashlib.sha256("\n".join(lines).encode()).hexdigest()[:12]
    batch_dir.mkdir(parents=True, exist_ok=True)
    req_path = batch_dir / f"requests_{fp}.jsonl"
    info_path = batch_dir / f"batch_{fp}.json"
    raw_path = batch_dir / f"results_raw_{fp}.jsonl"
    print(f"Batch request-set fingerprint: {fp} ({len(lines)} requests)")

    if not req_path.exists():
        req_path.write_text("\n".join(lines) + "\n")

    if info_path.exists():
        info = json.loads(info_path.read_text())
        print(f"Resuming batch {info['batch_id']} (submitted {info['submitted_ts']})")
    else:
        up = client.files.create(file=req_path.open("rb"), purpose="batch")
        batch = client.batches.create(input_file_id=up.id, endpoint=ENDPOINT,
                                      completion_window="24h", metadata=metadata or {})
        info = {"batch_id": batch.id, "input_file_id": up.id, "endpoint": ENDPOINT,
                "n_requests": len(lines), "fingerprint": fp,
                "submitted_ts": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        info_path.write_text(json.dumps(info, indent=2))
        print(f"Submitted batch {info['batch_id']}")

    batch = _poll(client, info["batch_id"], poll_interval_s, max_total_wait_s)
    if batch.status in RUNNING:
        raise ToolkitError(f"Batch {batch.id} still running (status={batch.status}) after "
                           f"{max_total_wait_s:.0f}s. Re-run the same command to resume polling.")
    if batch.status not in COLLECTABLE:                 # failed / cancelled: nothing collectable
        raise ToolkitError(f"Batch {batch.id} ended status={batch.status}; "
                           f"errors={getattr(batch, 'errors', None)}. Nothing collected. "
                           f"Inspect + fix, then delete {info_path} to resubmit.")

    if not raw_path.exists():
        if not batch.output_file_id:
            raise ToolkitError(f"Batch {batch.id} status={batch.status} has no output file "
                               f"(error_file_id={getattr(batch, 'error_file_id', None)}); cannot collect.")
        tmp = raw_path.with_name(raw_path.name + ".tmp")   # atomic: a truncated download must not
        tmp.write_text(client.files.content(batch.output_file_id).text)
        tmp.rename(raw_path)                               # be mistaken for the full result set

    # failed requests land in error_file_id, NOT in the output file — report them, never cache them
    failures: list[tuple[str, str]] = []
    if getattr(batch, "error_file_id", None):
        for line in (json.loads(ln) for ln in client.files.content(batch.error_file_id).text.splitlines()
                     if ln.strip()):
            err = line.get("error") or (line.get("response") or {}).get("body")
            failures.append((line.get("custom_id"), json.dumps(err)[:200]))

    results: dict[str, tuple[dict, dict]] = {}
    for line in (json.loads(ln) for ln in raw_path.read_text().splitlines() if ln.strip()):
        cid = line["custom_id"]
        resp = line.get("response") or {}
        if line.get("error") or resp.get("status_code") != 200:
            failures.append((cid, json.dumps(line.get("error") or resp.get("status_code"))[:200]))
            continue
        try:
            parsed = json.loads(output_text_from_body(resp["body"]))
        except (RuntimeError, json.JSONDecodeError) as e:  # refusal / malformed output: report,
            failures.append((cid, f"{type(e).__name__}: {e}"))  # don't orphan the good lines after it
            continue
        results[cid] = (parsed, usage_from_body(resp["body"]))
    return results, failures
