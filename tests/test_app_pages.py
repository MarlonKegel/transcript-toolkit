"""The app end to end: a real server, real pages, a real workspace.

Started the way the launcher starts it, then asked for every page. This is what catches a page
that raises only once something is actually rendered — the failure a user would meet as a
blank screen.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from transcript_toolkit import __version__
from transcript_toolkit.app import content

FIXTURES = Path(__file__).parent / "fixtures"
START_TIMEOUT_S = 60.0


def app_env() -> dict:
    """The environment the app is normally started in.

    NiceGUI treats PYTEST_CURRENT_TEST as "I am inside a test run" and then insists on a port
    from its own screen-test harness, so a plainly-launched app must not inherit it.
    """
    env = dict(os.environ)
    env.pop("PYTEST_CURRENT_TEST", None)
    return env


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get(port: int, path: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=10) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


@pytest.fixture(scope="module")
def workspace(tmp_path_factory):
    from transcript_toolkit.project import init_project
    from transcript_toolkit.steps.import_ import run_import

    project = init_project(str(tmp_path_factory.mktemp("app") / "ws"))
    for docx in FIXTURES.glob("*.docx"):
        shutil.copy(docx, project.data_dir)
    run_import(project)
    (project.diags_dir / "clip").mkdir(parents=True)
    (project.diags_dir / "clip" / "index.html").write_text("<h1>review</h1>")
    (project.root / "secret.txt").write_text("not for the browser")
    return project


@pytest.fixture(scope="module")
def server(workspace):
    port = free_port()
    process = subprocess.Popen(
        [sys.executable, "-m", "transcript_toolkit.cli", "app", "--no-browser",
         "--port", str(port), "--project", str(workspace.root)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=app_env())
    deadline = time.time() + START_TIMEOUT_S
    while time.time() < deadline:
        if process.poll() is not None:
            pytest.fail(f"the app exited at once:\n{process.stdout.read()}")
        try:
            status, body = get(port, "/api/health")
            if status == 200:
                break
        except OSError:
            time.sleep(0.2)
    else:
        process.kill()
        pytest.fail("the app did not start in time")
    yield port
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


def test_health_identifies_this_app_and_version(server, workspace):
    status, body = get(server, "/api/health")
    assert status == 200
    data = json.loads(body)
    assert data == {"app": "transcript-toolkit", "version": __version__, "port": server,
                    "workspace": str(workspace.root)}


@pytest.mark.parametrize("path", ["/", "/workspace", "/export", "/settings",
                                  *[f"/step/{s.slug}" for s in content.STEPS]])
def test_every_page_renders(server, path):
    status, body = get(server, path)
    assert status == 200
    assert "Transcript Toolkit" in body


def test_the_dashboard_names_the_next_thing_to_do(server):
    _, body = get(server, "/")
    assert "Next" in body
    assert "Add your OpenAI key" in body          # no key in a fresh workspace


def test_a_step_page_offers_the_demo_first(server):
    _, body = get(server, "/step/clip")
    assert "Run the demo" in body and "Run on the whole corpus" in body


def test_the_topics_page_explains_itself_when_there_is_no_topic_list(server):
    _, body = get(server, "/step/topics")
    assert "No topic list yet" in body


def test_an_unknown_step_says_so_instead_of_failing(server):
    status, body = get(server, "/step/nonsense")
    assert status == 200 and "No step called" in body


def test_review_pages_are_served_from_the_workspace(server):
    status, body = get(server, "/diags/clip/index.html")
    assert status == 200 and "review" in body


def test_the_diags_route_cannot_be_walked_out_of(server):
    """It serves one folder of the open workspace and nothing else."""
    for attempt in ("/diags/../secret.txt", "/diags/../../etc/passwd",
                    "/diags/clip/../../secret.txt"):
        status, _ = get(server, attempt)
        assert status == 404, attempt


def test_quitting_needs_the_toolkits_own_header(server):
    """A web page the user happens to have open must not be able to stop a corpus run: a
    cross-origin POST cannot carry a custom header."""
    request = urllib.request.Request(f"http://127.0.0.1:{server}/api/quit", method="POST")
    try:
        urllib.request.urlopen(request, timeout=10)
        pytest.fail("an unmarked POST was accepted")
    except urllib.error.HTTPError as e:
        assert e.code == 403
    assert get(server, "/api/health")[0] == 200          # still running


def test_a_second_start_hands_over_to_the_running_one(server, workspace):
    """Double-clicking the launcher again must not start a second server."""
    result = subprocess.run(
        [sys.executable, "-m", "transcript_toolkit.cli", "app", "--no-browser",
         "--port", str(server), "--project", str(workspace.root)],
        capture_output=True, text=True, timeout=60, env=app_env())
    assert result.returncode == 0
    assert "already running" in result.stdout
    assert get(server, "/api/health")[0] == 200          # still the original


def test_a_port_someone_else_holds_is_reported_with_the_way_out(workspace):
    with socket.socket() as squatter:
        squatter.bind(("127.0.0.1", 0))
        squatter.listen(1)
        port = squatter.getsockname()[1]
        result = subprocess.run(
            [sys.executable, "-m", "transcript_toolkit.cli", "app", "--no-browser",
             "--port", str(port), "--project", str(workspace.root)],
            capture_output=True, text=True, timeout=60, env=app_env())
    assert result.returncode == 2
    assert "already used by another program" in result.stderr
    assert f"--port {port + 1}" in result.stderr
