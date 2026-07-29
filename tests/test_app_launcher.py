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
    # the log folder is made before the redirect needs it, not inside the redirected group
    assert body.index(f"/bin/mkdir -p '{LOG.parent}'") < body.index(f"> '{LOG}'")


def test_the_launcher_waits_and_reports_a_server_that_never_starts():
    """A double-click that silently does nothing is the one failure this audience cannot
    recover from, so the applet waits for a sign of life and shows the log if none comes."""
    script = launcher.applescript(COMMAND, LOG)
    body = [line for line in script.splitlines() if "do shell script" in line][0]
    assert "/api/health" in body and "transcript-toolkit" in body
    assert f"/usr/bin/tail -15 '{LOG}' >&2" in body
    assert "exit 1" in body
    assert str(LOG) in script.split("display alert")[1]         # and where to read it in full


def test_paths_are_quoted_for_the_shell():
    script = launcher.applescript(Path("/Users/a b/bin/toolkit"), Path("/Users/a b/log.txt"))
    assert "'/Users/a b/bin/toolkit'" in script and "'/Users/a b/log.txt'" in script


def test_a_chosen_port_is_baked_in():
    assert "--port 9001" in launcher.applescript(COMMAND, LOG, port=9001)
    assert "--port" not in launcher.applescript(COMMAND, LOG)


def test_failure_is_shown_to_the_user_not_swallowed():
    script = launcher.applescript(COMMAND, LOG)
    assert "on error errMsg" in script
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
    monkeypatch.setattr(launcher, "candidate_dirs", lambda: [tmp_path / "Applications"])
    monkeypatch.setattr(launcher, "log_path", lambda: tmp_path / "Logs" / "launch.log")
    bundle = launcher.install_launcher()
    assert (bundle / "Contents" / "MacOS" / "applet").exists()
    assert (bundle / "Contents" / "Resources" / "applet.icns").exists()
    assert not (bundle / "Contents" / "Resources" / "Assets.car").exists()


# --- which Applications folder --------------------------------------------------------------
#
# Finder's sidebar "Applications" is /Applications. ~/Applications is a different folder that
# looks identical in the message and is nowhere in the sidebar — the first place anybody looks
# is the one they can see.

def test_it_goes_to_the_applications_people_can_see(monkeypatch, tmp_path):
    shared = tmp_path / "Applications"
    shared.mkdir()
    monkeypatch.setattr(launcher, "candidate_dirs",
                        lambda: [shared, tmp_path / "home" / "Applications"])
    assert launcher.install_dir() == shared


def test_a_locked_down_mac_falls_back_to_the_users_own_folder(monkeypatch, tmp_path):
    """On a managed machine /Applications is not writable by a standard user."""
    shared, personal = tmp_path / "Applications", tmp_path / "home" / "Applications"
    shared.mkdir()
    shared.chmod(0o555)
    monkeypatch.setattr(launcher, "candidate_dirs", lambda: [shared, personal])
    try:
        assert launcher.install_dir() == personal
    finally:
        shared.chmod(0o755)


def test_the_message_says_how_to_reach_the_folder_it_actually_used(tmp_path):
    shared = launcher.where_to_find(Path("/Applications") / f"{launcher.APP_NAME}.app")
    assert "sidebar" in shared

    personal = launcher.where_to_find(Path.home() / "Applications" / f"{launcher.APP_NAME}.app")
    assert "NOT the Applications in Finder's sidebar" in personal
    assert str(Path.home() / "Applications") in personal
    assert "Command-Space" in personal          # the way that works wherever it ended up


def test_an_older_copy_in_the_other_folder_is_taken_away(monkeypatch, tmp_path):
    """Two apps of the same name is how somebody double-clicks last month's version for a
    week without noticing."""
    shared, personal = tmp_path / "Applications", tmp_path / "home" / "Applications"
    for folder in (shared, personal):
        folder.mkdir(parents=True)
    stale = personal / f"{launcher.APP_NAME}.app"
    (stale / "Contents").mkdir(parents=True)
    (stale / "Contents" / "Info.plist").write_text(
        f"<plist><dict><key>CFBundleIdentifier</key><string>{launcher.BUNDLE_ID}</string>"
        f"</dict></plist>")
    monkeypatch.setattr(launcher, "candidate_dirs", lambda: [shared, personal])

    launcher._remove_older_copies(shared / f"{launcher.APP_NAME}.app")
    assert not stale.exists()


def test_something_else_with_the_same_name_is_left_alone(monkeypatch, tmp_path):
    """Never delete an app somebody else put there just because the name matches."""
    shared, personal = tmp_path / "Applications", tmp_path / "home" / "Applications"
    for folder in (shared, personal):
        folder.mkdir(parents=True)
    theirs = personal / f"{launcher.APP_NAME}.app"
    (theirs / "Contents").mkdir(parents=True)
    (theirs / "Contents" / "Info.plist").write_text("<plist><dict/></plist>")
    monkeypatch.setattr(launcher, "candidate_dirs", lambda: [shared, personal])

    launcher._remove_older_copies(shared / f"{launcher.APP_NAME}.app")
    assert theirs.exists()


def test_the_settings_page_names_wherever_it_ended_up(monkeypatch, tmp_path):
    shared, personal = tmp_path / "Applications", tmp_path / "home" / "Applications"
    personal.mkdir(parents=True)
    (personal / f"{launcher.APP_NAME}.app").mkdir()
    monkeypatch.setattr(launcher, "candidate_dirs", lambda: [shared, personal])
    assert launcher.app_path() == personal / f"{launcher.APP_NAME}.app"
    assert launcher.installed_path() == personal / f"{launcher.APP_NAME}.app"
