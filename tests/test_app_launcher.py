"""The generated Mac launcher.

Only the parts that can be checked anywhere: what gets written into the applet, and that it
refuses to pretend on a machine that has no Applications folder. Whether macOS then opens it
without complaint is what scripts/mac_launcher_smoke_test.sh established on real hardware.
"""
import sys
from pathlib import Path

import pytest

from transcript_toolkit.app import launcher
from transcript_toolkit.errors import ToolkitError

COMMAND = Path("/Users/someone/.local/bin/toolkit")
LOG = Path("/Users/someone/Library/Logs/transcript-toolkit/launch.log")


def test_the_applet_calls_the_command_by_its_full_path():
    """An app opened from Finder gets a bare PATH that does not include ~/.local/bin, so the
    launcher cannot rely on the name alone."""
    script = launcher.applescript(COMMAND, LOG)
    assert f"'{COMMAND}' app --from-launcher" in script
    assert "toolkit app" not in script.replace(str(COMMAND), "")


def test_the_server_is_detached_with_its_output_redirected():
    """Backgrounded and fully redirected, or the launcher would sit in the Dock waiting for a
    server that runs for hours."""
    script = launcher.applescript(COMMAND, LOG)
    assert script.rstrip().endswith("end run")
    body = [line for line in script.splitlines() if "do shell script" in line][0]
    assert f"> '{LOG}' 2>&1 &" in body
    assert f"/bin/mkdir -p '{LOG.parent}'" in body


def test_paths_are_quoted_for_the_shell():
    script = launcher.applescript(Path("/Users/a b/bin/toolkit"), Path("/Users/a b/log.txt"))
    assert "'/Users/a b/bin/toolkit'" in script and "'/Users/a b/log.txt'" in script


def test_a_chosen_port_is_baked_in():
    assert "--port 9001" in launcher.applescript(COMMAND, LOG, port=9001)
    assert "--port" not in launcher.applescript(COMMAND, LOG)


def test_failure_is_shown_to_the_user_not_swallowed():
    script = launcher.applescript(COMMAND, LOG)
    assert "on error errMsg number errNum" in script
    assert "display alert" in script


def test_installing_is_refused_off_macos(monkeypatch):
    monkeypatch.setattr(launcher.sys, "platform", "linux")
    with pytest.raises(ToolkitError, match="macOS"):
        launcher.install_launcher()


def test_a_missing_toolkit_command_says_how_to_install_it(monkeypatch):
    monkeypatch.setattr(launcher.shutil, "which", lambda name: None)
    with pytest.raises(ToolkitError, match="uv tool install"):
        launcher.toolkit_command()


def test_the_command_is_found_on_the_path(monkeypatch, tmp_path):
    real = tmp_path / "toolkit"
    real.write_text("#!/bin/sh\n")
    monkeypatch.setattr(launcher.shutil, "which",
                        lambda name: str(real) if name == "toolkit" else None)
    assert launcher.toolkit_command() == real.resolve()


def test_the_icon_ships_with_the_package():
    """package-data globs are per-directory, so defaults/app/ needs its own line in
    pyproject.toml — without it the icon is missing from an installed copy, not from here."""
    from importlib import resources
    icon = resources.files("transcript_toolkit") / "defaults" / "app" / "icon.png"
    assert icon.is_file()
    assert icon.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.skipif(sys.platform != "darwin", reason="builds a real .app")
def test_it_really_builds_on_a_mac(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "applications_dir", lambda: tmp_path / "Applications")
    monkeypatch.setattr(launcher, "app_path",
                        lambda: tmp_path / "Applications" / f"{launcher.APP_NAME}.app")
    monkeypatch.setattr(launcher, "log_path", lambda: tmp_path / "Logs" / "launch.log")
    bundle = launcher.install_launcher()
    assert (bundle / "Contents" / "MacOS" / "applet").exists()
    assert (bundle / "Contents" / "Resources" / "applet.icns").exists()
    assert not (bundle / "Contents" / "Resources" / "Assets.car").exists()
