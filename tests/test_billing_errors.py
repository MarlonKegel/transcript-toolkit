"""An account that cannot be billed refuses every call. What the curator sees when that happens.

Two things have to be true. The message has to name the real problem — an empty credit balance
and a spending limit that has been hit arrive as different codes but read identically in OpenAI's
own wording, which points at the wrong page. And the refusal has to be immediate: the commonest
code comes back as HTTP 429, the same class as a genuine rate limit, so the retry ladder would
otherwise spend minutes per call, on every worker, waiting for credit to appear.
"""
import json
from types import SimpleNamespace

import httpx
import openai
import pytest

from transcript_toolkit.core import llm
from transcript_toolkit.core.batch import run_batch
from transcript_toolkit.errors import ToolkitError


def api_error(cls, status, code, error_type, message="nope"):
    """The exception the OpenAI SDK raises for a given error body."""
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    return cls(message, response=httpx.Response(status, request=request),
               body={"message": message, "type": error_type, "param": None, "code": code})


OUT_OF_CREDIT = lambda: api_error(                                          # noqa: E731
    openai.RateLimitError, 429, "insufficient_quota", "insufficient_quota",
    "You exceeded your current quota, please check your plan and billing details.")

LIMIT_REACHED = lambda: api_error(                                          # noqa: E731
    openai.BadRequestError, 400, "billing_hard_limit_reached", "billing_limit_user_error",
    "Billing hard limit has been reached.")

REAL_RATE_LIMIT = lambda: api_error(                                        # noqa: E731
    openai.RateLimitError, 429, "rate_limit_exceeded", "requests",
    "Rate limit reached for gpt-5.4-mini.")


# --- what the message says --------------------------------------------------------------------

@pytest.mark.parametrize("make,expected", [(OUT_OF_CREDIT, "out of credit"),
                                           (LIMIT_REACHED, "billing limit")])
def test_a_billing_refusal_is_explained(make, expected):
    refusal = llm.billing_refusal(make())
    assert isinstance(refusal, ToolkitError)
    message = str(refusal)
    assert expected in message
    assert "settings/organization/billing" in message      # where the balance is
    assert "settings/organization/limits" in message       # where the limits are
    assert "carry on from where it stopped" in message     # nothing is lost
    assert "not about anything you did" in message         # not the curator's mistake


def test_the_message_mentions_the_auto_recharge_trap():
    """The failure that actually happened: auto-recharge on, balance empty, because the bank
    declines an unattended charge. Nothing in OpenAI's UI says so."""
    message = str(llm.billing_refusal(OUT_OF_CREDIT()))
    assert "auto-recharge" in message
    assert "by hand" in message


def test_other_problems_are_not_mistaken_for_billing():
    assert llm.billing_refusal(REAL_RATE_LIMIT()) is None
    assert llm.billing_refusal(RuntimeError("something else")) is None


# --- it must not retry -----------------------------------------------------------------------

def test_a_billing_refusal_fails_at_once(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep",
                        lambda s: pytest.fail(f"slept {s}s waiting for credit to appear"))
    calls = []

    def refuse():
        calls.append(1)
        raise OUT_OF_CREDIT()

    with pytest.raises(ToolkitError) as e:
        llm._retry(refuse, what="create")
    assert "out of credit" in str(e.value)
    assert len(calls) == 1, "the call was retried"


def test_a_genuine_rate_limit_is_still_retried(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    attempts = []

    def flaky():
        attempts.append(1)
        if len(attempts) < 3:
            raise REAL_RATE_LIMIT()
        return "done"

    assert llm._retry(flaky, what="create") == "done"
    assert len(attempts) == 3


def test_an_unrelated_error_is_not_swallowed(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    with pytest.raises(ValueError, match="bad schema"):
        llm._retry(lambda: (_ for _ in ()).throw(ValueError("bad schema")), what="create")


# --- the context manager, and the batch path ------------------------------------------------

def test_billing_errors_explained_leaves_everything_else_alone():
    with pytest.raises(ToolkitError, match="out of credit"):
        with llm.billing_errors_explained():
            raise OUT_OF_CREDIT()

    with pytest.raises(KeyError):
        with llm.billing_errors_explained():
            raise KeyError("untouched")


def test_a_refused_batch_submission_is_explained(tmp_path):
    """Batch submission is billable too, and it is the path a full corpus run takes."""
    def refuse(file, purpose):
        raise OUT_OF_CREDIT()

    client = SimpleNamespace(files=SimpleNamespace(create=refuse), batches=SimpleNamespace())
    units = [{"custom_id": "a", "instructions": "I", "user_content": "hi",
              "schema": {"type": "json_schema", "name": "s", "schema": {}, "strict": True},
              "model": "gpt-5.4-mini", "reasoning": "low", "verbosity": "low",
              "prompt_cache_key": "pck"}]

    with pytest.raises(ToolkitError) as e:
        run_batch(client, units, tmp_path / "batch")
    assert "out of credit" in str(e.value)
    assert "settings/organization/billing" in str(e.value)


def test_the_requests_file_survives_a_refusal(tmp_path):
    """It is written before submission, so the retry after the account is fixed reuses it
    rather than rebuilding — and the fingerprint stays the same."""
    def refuse(file, purpose):
        raise OUT_OF_CREDIT()

    client = SimpleNamespace(files=SimpleNamespace(create=refuse), batches=SimpleNamespace())
    units = [{"custom_id": "a", "instructions": "I", "user_content": "hi",
              "schema": {"type": "json_schema", "name": "s", "schema": {}, "strict": True},
              "model": "gpt-5.4-mini", "reasoning": "low", "verbosity": "low",
              "prompt_cache_key": "pck"}]
    batch_dir = tmp_path / "batch"

    with pytest.raises(ToolkitError):
        run_batch(client, units, batch_dir)

    written = list(batch_dir.glob("requests_*.jsonl"))
    assert len(written) == 1
    assert json.loads(written[0].read_text().splitlines()[0])["custom_id"] == "a"
    assert not list(batch_dir.glob("batch_*.json")), "nothing was submitted, so nothing to resume"
