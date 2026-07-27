"""LLM plumbing: client, structured-output schema, background-mode call with polling.

Ported from the working repo (tag-topics/summarize utils variant — the richest one).
Background mode is load-bearing: the sync path holds one HTTP connection through the whole
model compute and gets dropped by a middlebox after ~60s idle on long reasoning calls, so
every call is `responses.create(background=True)` + polling on `responses.retrieve`.
NotFoundError is retried: a just-created background response can briefly 404 on retrieve
(eventual consistency).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from ..errors import ToolkitError

REASONING_LEVELS = ("none", "low", "medium", "high", "xhigh")
VERBOSITY_LEVELS = ("low", "medium", "high")

TERMINAL_OK = "completed"
TERMINAL_BAD = ("failed", "cancelled", "incomplete")


def openai_client(project_root: Path, timeout: float = 300.0, max_retries: int = 0):
    from dotenv import load_dotenv
    load_dotenv(project_root / ".env")
    if not os.environ.get("OPENAI_API_KEY"):
        raise ToolkitError(f"OPENAI_API_KEY not set; put it in {project_root / '.env'}")
    from openai import OpenAI
    return OpenAI(timeout=timeout, max_retries=max_retries)


def check_levels(reasoning: str, verbosity: str) -> None:
    if reasoning not in REASONING_LEVELS:
        raise ToolkitError(f"Unknown reasoning level {reasoning!r}; expected one of {list(REASONING_LEVELS)}")
    if verbosity not in VERBOSITY_LEVELS:
        raise ToolkitError(f"Unknown verbosity {verbosity!r}; expected one of {list(VERBOSITY_LEVELS)}")


def build_schema(model_cls, name: str) -> dict:
    from openai.lib._pydantic import to_strict_json_schema
    return {"type": "json_schema", "name": name,
            "schema": to_strict_json_schema(model_cls), "strict": True}


def _transient_errors() -> tuple:
    from openai import APIConnectionError, APITimeoutError, NotFoundError, RateLimitError
    return (APIConnectionError, APITimeoutError, RateLimitError, NotFoundError)


def _extract_output_text(response) -> str:
    for item in response.output:
        if getattr(item, "type", None) == "message":
            for c in item.content:
                if getattr(c, "type", None) == "output_text":
                    return c.text
        if getattr(item, "type", None) == "refusal":
            raise RuntimeError(f"Model refused: {getattr(item, 'refusal', item)}")
    raise RuntimeError(f"No output_text in response: {response}")


def _retry(fn, *, what: str, max_retries: int = 6, base_backoff: float = 4.0):
    transient = _transient_errors()
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except transient as e:
            if attempt == max_retries:
                raise
            sleep_s = base_backoff * (2 ** attempt)
            print(f"    {what} {type(e).__name__} (attempt {attempt + 1}/{max_retries + 1}); sleeping {sleep_s:.0f}s")
            time.sleep(sleep_s)


def call_llm(client, model, reasoning, verbosity, schema, instructions, user_content,
             prompt_cache_key_str, poll_interval_s: float = 4.0,
             max_total_wait_s: float = 600.0, heartbeat_after_s: float = 90.0,
             heartbeat_every_s: float = 60.0) -> tuple[dict, dict]:
    """Background-mode structured-output call + polling. Returns (parsed_json, usage_dict).

    A call that takes unusually long says so (heartbeat) instead of looking frozen, and one that
    never returns gives up rather than blocking the whole run: every finished call is already in
    the cache, so re-running the command retries only what is missing."""
    resp = _retry(lambda: client.responses.create(
        model=model, instructions=instructions, input=user_content,
        reasoning={"effort": reasoning}, text={"verbosity": verbosity, "format": schema},
        prompt_cache_key=prompt_cache_key_str, background=True,
    ), what="create")
    response_id = resp.id

    t0 = time.monotonic()
    next_beat = heartbeat_after_s
    while resp.status not in (TERMINAL_OK, *TERMINAL_BAD):
        elapsed = time.monotonic() - t0
        if elapsed > max_total_wait_s:
            raise RuntimeError(
                f"No response after {elapsed:.0f}s (status={resp.status}, id={response_id}). "
                f"Giving up on this call so the run doesn't hang — every call that DID finish is "
                f"cached, so re-running the same command retries only the unfinished ones.")
        if elapsed >= next_beat:                 # a slow call announces itself; silence != frozen
            print(f"    still waiting on a {model} call ({elapsed:.0f}s elapsed, "
                  f"status={resp.status})", flush=True)
            next_beat = elapsed + heartbeat_every_s
        time.sleep(poll_interval_s)
        resp = _retry(lambda: client.responses.retrieve(response_id), what="retrieve")

    if resp.status != TERMINAL_OK:
        raise RuntimeError(f"Response {response_id} ended status={resp.status}; "
                           f"error={getattr(resp, 'error', None)}")

    parsed = json.loads(_extract_output_text(resp))
    u = resp.usage
    usage = {
        "input_tokens": getattr(u, "input_tokens", None),
        "output_tokens": getattr(u, "output_tokens", None),
        "reasoning_tokens": getattr(getattr(u, "output_tokens_details", None), "reasoning_tokens", None),
        "cached_input_tokens": getattr(getattr(u, "input_tokens_details", None), "cached_tokens", None),
    }
    return parsed, usage
