"""The update notice: never wrong, never noisy, never fatal."""
import json
import time

import pytest

import transcript_toolkit.core.update as upd


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(upd, "_cache_path", lambda: tmp_path / "update_check.json")
    monkeypatch.delenv("TOOLKIT_NO_UPDATE_CHECK", raising=False)


def test_parse_and_compare_versions():
    assert upd.parse_version('__version__ = "1.2.3"\n') == "1.2.3"
    assert upd.parse_version("nothing here") is None
    assert upd.version_tuple("0.1.10") > upd.version_tuple("0.1.9")   # numeric, not string, order
    assert upd.version_tuple("0.2.0") > upd.version_tuple("0.1.99")


def test_notice_when_newer_available(monkeypatch):
    monkeypatch.setattr(upd, "_fetch_latest", lambda: "0.1.9")
    notice = upd.update_notice(current="0.1.2")
    assert "0.1.2 -> 0.1.9" in notice
    assert upd.UPGRADE_COMMAND in notice


@pytest.mark.parametrize("latest", ["0.1.2", "0.1.1", None])
def test_no_notice_when_current_or_unknown(monkeypatch, latest):
    monkeypatch.setattr(upd, "_fetch_latest", lambda: latest)
    assert upd.update_notice(current="0.1.2") is None


def test_network_failure_is_silent(monkeypatch):
    def boom():
        raise OSError("no network")
    monkeypatch.setattr(upd, "_fetch_latest", boom)
    assert upd.update_notice(current="0.1.0") is None      # must never break a command


def test_opt_out_env_skips_entirely(monkeypatch):
    monkeypatch.setenv("TOOLKIT_NO_UPDATE_CHECK", "1")
    monkeypatch.setattr(upd, "_fetch_latest",
                        lambda: pytest.fail("must not touch the network when opted out"))
    assert upd.update_notice(current="0.1.0") is None


def test_result_is_cached_for_a_day(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(upd, "_fetch_latest", lambda: calls.append(1) or "0.9.9")
    assert upd.latest_version() == "0.9.9"
    assert upd.latest_version() == "0.9.9"                 # served from cache
    assert len(calls) == 1
    # an expired cache is refetched
    path = upd._cache_path()
    stale = json.loads(path.read_text())
    stale["checked_at"] = time.time() - (upd.CHECK_EVERY_S + 1)
    path.write_text(json.dumps(stale))
    assert upd.latest_version() == "0.9.9"
    assert len(calls) == 2


def test_corrupt_cache_is_survivable(monkeypatch):
    monkeypatch.setattr(upd, "_fetch_latest", lambda: "0.9.9")
    upd._cache_path().parent.mkdir(parents=True, exist_ok=True)
    upd._cache_path().write_text("{not json")
    assert upd.latest_version() == "0.9.9"
