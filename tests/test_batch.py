import json
from types import SimpleNamespace

import pytest

from transcript_toolkit.core.batch import run_batch
from transcript_toolkit.errors import ToolkitError


def unit(cid, text="hello"):
    return {"custom_id": cid, "instructions": "INSTR", "user_content": text,
            "schema": {"type": "json_schema", "name": "clip_locations", "schema": {}, "strict": True},
            "model": "gpt-5.4-mini", "reasoning": "medium", "verbosity": "low",
            "prompt_cache_key": "pck"}


def ok_line(cid, payload):
    return json.dumps({"custom_id": cid, "response": {"status_code": 200, "body": {
        "output": [{"type": "message",
                    "content": [{"type": "output_text", "text": json.dumps(payload)}]}],
        "usage": {"input_tokens": 100, "output_tokens": 10,
                  "output_tokens_details": {"reasoning_tokens": 3},
                  "input_tokens_details": {"cached_tokens": 80}}}}})


class FakeClient:
    """Just enough of the OpenAI client surface for run_batch: files.create/content +
    batches.create/retrieve. Statuses pop from a scripted sequence."""

    def __init__(self, statuses, output_lines=None, error_lines=None):
        self.statuses = list(statuses)
        self.file_store = {"file-out": "\n".join(output_lines or []),
                           "file-err": "\n".join(error_lines or [])}
        self.n_files_created = 0
        self.n_batches_created = 0
        self.files = SimpleNamespace(create=self._files_create, content=self._files_content)
        self.batches = SimpleNamespace(create=self._batches_create, retrieve=self._batches_retrieve)

    def _files_create(self, file, purpose):
        assert purpose == "batch"
        self.n_files_created += 1
        self.uploaded = file.read()
        return SimpleNamespace(id="file-in")

    def _files_content(self, file_id):
        return SimpleNamespace(text=self.file_store[file_id])

    def _batches_create(self, input_file_id, endpoint, completion_window, metadata):
        assert endpoint == "/v1/responses" and completion_window == "24h"
        self.n_batches_created += 1
        return SimpleNamespace(id="batch-1", status="validating")

    def _batches_retrieve(self, batch_id):
        status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        has_errors = bool(self.file_store["file-err"])
        return SimpleNamespace(
            id=batch_id, status=status,
            request_counts=SimpleNamespace(total=2, completed=2, failed=0),
            output_file_id="file-out" if status in ("completed", "expired") else None,
            error_file_id="file-err" if has_errors else None, errors=None)


def test_request_building_and_happy_path(tmp_path):
    units = [unit("clip-b", "second"), unit("clip-a", "first")]
    lines = [ok_line("clip-a", {"countries": [], "regions": []}),
             ok_line("clip-b", {"countries": [{"place": "Rio", "country": "Brazil"}], "regions": []})]
    client = FakeClient(["in_progress", "completed"], output_lines=lines)
    results, failures = run_batch(client, units, tmp_path, poll_interval_s=0.01)

    assert failures == []
    assert set(results) == {"clip-a", "clip-b"}
    parsed, usage = results["clip-b"]
    assert parsed["countries"][0]["country"] == "Brazil"
    assert usage == {"input_tokens": 100, "output_tokens": 10,
                     "reasoning_tokens": 3, "cached_input_tokens": 80}

    # requests.jsonl: sorted by custom_id, full Responses-API body shape
    req_files = list(tmp_path.glob("requests_*.jsonl"))
    assert len(req_files) == 1
    reqs = [json.loads(ln) for ln in req_files[0].read_text().splitlines()]
    assert [r["custom_id"] for r in reqs] == ["clip-a", "clip-b"]
    body = reqs[1]["body"]
    assert (reqs[1]["method"], reqs[1]["url"]) == ("POST", "/v1/responses")
    assert body["model"] == "gpt-5.4-mini" and body["instructions"] == "INSTR"
    assert body["input"] == "second" and body["reasoning"] == {"effort": "medium"}
    assert body["text"]["verbosity"] == "low" and body["prompt_cache_key"] == "pck"
    assert client.uploaded == req_files[0].read_bytes()
    assert client.n_batches_created == 1
    assert list(tmp_path.glob("batch_*.json")) and list(tmp_path.glob("results_raw_*.jsonl"))


def test_resume_attaches_to_persisted_batch(tmp_path):
    units = [unit("clip-a")]
    lines = [ok_line("clip-a", {"countries": [], "regions": []})]
    first = FakeClient(["in_progress"], output_lines=lines)
    with pytest.raises(ToolkitError, match="still running"):
        run_batch(first, units, tmp_path, poll_interval_s=0.01, max_total_wait_s=0)
    assert first.n_batches_created == 1                    # submitted, then timed out polling

    # re-run with the same pending set: attaches to batch_{fp}.json instead of resubmitting
    second = FakeClient(["completed"], output_lines=lines)
    results, failures = run_batch(second, units, tmp_path, poll_interval_s=0.01)
    assert second.n_batches_created == 0 and second.n_files_created == 0
    assert set(results) == {"clip-a"} and failures == []

    # a third run parses the already-downloaded results without touching the API files again
    third = FakeClient(["completed"])
    third.file_store["file-out"] = ""                      # would yield nothing if re-downloaded
    results, _ = run_batch(third, units, tmp_path, poll_interval_s=0.01)
    assert set(results) == {"clip-a"}


def test_failed_requests_reported_not_cached(tmp_path):
    units = [unit("clip-a"), unit("clip-b"), unit("clip-c")]
    lines = [ok_line("clip-a", {"countries": [], "regions": []}),
             json.dumps({"custom_id": "clip-b", "response": {"status_code": 500, "body": {}}})]
    errs = [json.dumps({"custom_id": "clip-c", "error": {"message": "boom"}})]
    client = FakeClient(["completed"], output_lines=lines, error_lines=errs)
    results, failures = run_batch(client, units, tmp_path, poll_interval_s=0.01)
    assert set(results) == {"clip-a"}                      # only the success is returned
    assert {cid for cid, _ in failures} == {"clip-b", "clip-c"}


def test_batch_level_failure_raises(tmp_path):
    client = FakeClient(["failed"])
    with pytest.raises(ToolkitError, match="status=failed"):
        run_batch(client, [unit("clip-a")], tmp_path, poll_interval_s=0.01)


def test_refusal_line_becomes_failure(tmp_path):
    refusal = json.dumps({"custom_id": "clip-a", "response": {"status_code": 200, "body": {
        "output": [{"type": "refusal", "refusal": "no"}], "usage": {}}}})
    client = FakeClient(["completed"], output_lines=[refusal])
    results, failures = run_batch(client, [unit("clip-a")], tmp_path, poll_interval_s=0.01)
    assert results == {} and failures[0][0] == "clip-a" and "refused" in failures[0][1].lower()
