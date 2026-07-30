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
    assert "toolkit update" in notice


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


# --- toolkit update --------------------------------------------------------------------------

def test_update_command_shells_out_to_uv(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(upd.shutil if hasattr(upd, "shutil") else __import__("shutil"),
                        "which", lambda name: "/usr/bin/uv")
    import subprocess
    monkeypatch.setattr(subprocess, "run",
                        lambda cmd, **kw: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0))
    upd._cache_path().parent.mkdir(parents=True, exist_ok=True)
    upd._cache_path().write_text('{"checked_at": 0, "latest": "9.9.9"}')

    upd.run_update()
    assert calls == [["/usr/bin/uv", "tool", "upgrade", "transcript-toolkit"]]
    assert not upd._cache_path().exists()          # stale "newer version available" note cleared
    assert "toolkit --version" in capsys.readouterr().out


def test_update_without_uv_explains_rather_than_guessing(monkeypatch):
    from transcript_toolkit.errors import ToolkitError
    monkeypatch.setattr(upd, "uv_path", lambda: None)
    with pytest.raises(ToolkitError, match="uv is not installed"):
        upd.run_update()


def test_uv_is_found_where_it_lives_when_it_is_not_on_the_path(monkeypatch, tmp_path):
    """A Mac app opened from the Dock inherits launchd's PATH — /usr/bin:/bin:/usr/sbin:/sbin —
    so uv is not on it and the update button could only ever fail. Looking in the places uv
    installs itself is what makes the button work from the Dock as well as from Terminal."""
    import shutil as _shutil

    bin_dir = tmp_path / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    uv = bin_dir / "uv"
    uv.write_text("#!/bin/sh\n")
    uv.chmod(0o755)

    monkeypatch.setattr(_shutil, "which", lambda name: None)     # nothing on PATH
    monkeypatch.setattr(upd, "UV_DIRS", (str(bin_dir),))
    assert upd.uv_path() == str(uv)

    monkeypatch.setattr(upd, "UV_DIRS", (str(tmp_path / "nowhere"),))
    assert upd.uv_path() is None


def test_the_uv_on_the_path_wins(monkeypatch):
    """Whoever is typing has a PATH, and the uv on it is the one they mean."""
    import shutil as _shutil

    monkeypatch.setattr(_shutil, "which", lambda name: "/somewhere/else/uv")
    assert upd.uv_path() == "/somewhere/else/uv"


def test_the_upgrade_runs_the_uv_that_was_found(monkeypatch):
    """Not the bare word `uv`: with no PATH to resolve it against, that is the failure again."""
    import subprocess

    seen = []
    monkeypatch.setattr(upd, "uv_path", lambda: "/opt/homebrew/bin/uv")
    monkeypatch.setattr(subprocess, "run",
                        lambda cmd, **kw: seen.append(cmd) or subprocess.CompletedProcess(cmd, 0))
    upd.run_update()
    assert seen == [["/opt/homebrew/bin/uv", "tool", "upgrade", "transcript-toolkit"]]


def test_failed_upgrade_is_reported(monkeypatch):
    import shutil as _shutil
    import subprocess
    from transcript_toolkit.errors import ToolkitError
    monkeypatch.setattr(_shutil, "which", lambda name: "/usr/bin/uv")
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1))
    with pytest.raises(ToolkitError, match="could not upgrade"):
        upd.run_update()


def test_notice_points_at_the_toolkit_command(monkeypatch):
    monkeypatch.setattr(upd, "_fetch_latest", lambda: "9.9.9")
    assert "toolkit update" in upd.update_notice(current="0.1.0")


def test_uv_is_told_where_its_tools_go_when_there_is_no_shell(monkeypatch, tmp_path):
    """From the Dock, PATH is launchd's, so uv warns that installed tools will not be found and
    tells the reader to edit their shell profile. True of that PATH, irrelevant here — the app
    runs `toolkit` by absolute path — and confusing to whoever is watching the output."""
    import shutil as _shutil
    import subprocess

    seen = {}
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("UV_TOOL_BIN_DIR", str(tmp_path / "bin"))
    monkeypatch.setattr(_shutil, "which", lambda name: None)      # not on PATH: no shell
    monkeypatch.setattr(upd, "uv_path", lambda: "/somewhere/uv")
    monkeypatch.setattr(subprocess, "run",
                        lambda cmd, **kw: seen.update(kw) or subprocess.CompletedProcess(cmd, 0))
    upd.run_update()
    assert str(tmp_path / "bin") in seen["env"]["PATH"]


def test_a_real_shell_keeps_uvs_warning(monkeypatch):
    """In a terminal the same warning is real advice, so it is left alone."""
    import shutil as _shutil
    import subprocess

    seen = {}
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr(_shutil, "which", lambda name: "/usr/local/bin/uv")
    monkeypatch.setattr(subprocess, "run",
                        lambda cmd, **kw: seen.update(kw) or subprocess.CompletedProcess(cmd, 0))
    upd.run_update()
    assert seen["env"]["PATH"] == "/usr/bin:/bin"


def test_it_says_whether_anything_actually_changed(monkeypatch, capsys):
    """The app reads this line to decide whether to restart itself, so it is the toolkit's own
    words and not uv's prose."""
    import subprocess

    monkeypatch.setattr(upd, "uv_path", lambda: "/usr/bin/uv")
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0))

    monkeypatch.setattr(upd, "installed_version", lambda: "9.9.9")
    upd.run_update()
    assert f"{upd.UPDATED_MARKER} {upd.__version__} -> 9.9.9" in capsys.readouterr().out

    monkeypatch.setattr(upd, "installed_version", lambda: upd.__version__)
    upd.run_update()
    assert upd.UNCHANGED_MARKER in capsys.readouterr().out

    monkeypatch.setattr(upd, "installed_version", lambda: None)     # could not ask
    upd.run_update()
    assert upd.UNCHANGED_MARKER in capsys.readouterr().out


def test_the_new_version_is_read_from_a_fresh_process(monkeypatch, tmp_path):
    """This process loaded __version__ before the upgrade, so it cannot see the new code — only
    a subprocess of the command uv just replaced can."""
    import subprocess

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "toolkit").write_text("#!/bin/sh\n")
    monkeypatch.setenv("UV_TOOL_BIN_DIR", str(bin_dir))
    monkeypatch.setattr(
        subprocess, "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "transcript-toolkit 1.2.3\n", ""))
    assert upd.installed_version() == "1.2.3"

    monkeypatch.setenv("UV_TOOL_BIN_DIR", str(tmp_path / "nowhere"))
    assert upd.installed_version() is None
