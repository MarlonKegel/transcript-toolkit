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


def app_env(home: Path | None = None) -> dict:
    """The environment the app is normally started in.

    NiceGUI treats PYTEST_CURRENT_TEST as "I am inside a test run" and then insists on a port
    from its own screen-test harness, so a plainly-launched app must not inherit it.

    `home` moves the list of remembered projects into the test's own directory. The server runs
    as a real subprocess, so without it these tests would write test paths into the list of
    projects belonging to whoever ran them.
    """
    env = dict(os.environ)
    env.pop("PYTEST_CURRENT_TEST", None)
    if home is not None:
        env["HOME"] = str(home)
        env["XDG_CONFIG_HOME"] = str(home / ".config")
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

    # two topic lists, so the page has to keep them apart
    for name in ("collection", "filter"):
        (project.topics_dir / f"{name}.csv").write_text("name,description\nWork,About work\n")
    # and calls that have been paid for, so the cost report has something to report
    (project.cache_dir / "clip.jsonl").write_text(json.dumps({
        "cache_key": "a", "model": "gpt-5.6-sol", "reasoning_effort": "medium",
        "usage": {"input_tokens": 1_000_000, "cached_input_tokens": 0,
                  "reasoning_tokens": 0, "output_tokens": 100_000}}) + "\n")
    return project


@pytest.fixture(scope="module")
def fake_home(tmp_path_factory):
    home = tmp_path_factory.mktemp("home")
    (home / ".config").mkdir()
    return home


@pytest.fixture(scope="module")
def server(workspace, fake_home):
    port = free_port()
    process = subprocess.Popen(
        [sys.executable, "-m", "transcript_toolkit.cli", "app", "--no-browser",
         "--port", str(port), "--project", str(workspace.root)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=app_env(fake_home))
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


def test_health_identifies_this_app_and_version(server):
    status, body = get(server, "/api/health")
    assert status == 200
    data = json.loads(body)
    # Nothing more: the workspace path names a person's folder and no caller needs it.
    assert data == {"app": "transcript-toolkit", "version": __version__, "port": server}


@pytest.mark.parametrize("path", ["/", "/workspace", "/export", "/settings",
                                  *[f"/step/{s.slug}" for s in content.STEPS]])
def test_every_page_renders(server, path):
    status, body = get(server, path)
    assert status == 200
    assert "Transcript Toolkit" in body


def test_home_lists_the_projects_and_where_each_one_has_got_to(server, workspace):
    """Home is the landing page: every project the app knows, not one project's dashboard."""
    _, body = get(server, "/")
    assert "Your projects" in body
    assert "steps run on everything" in body
    assert "Start a new project" in body


def test_the_workspace_page_names_the_next_thing_to_do(server):
    _, body = get(server, "/workspace")
    assert "Next" in body
    assert "Add your OpenAI key" in body          # no key in a fresh workspace


def test_a_step_page_offers_only_the_demo_until_it_has_been_run(server):
    """Running the whole collection without a reviewed demo is refused by the toolkit, so the
    page does not offer it: the button appears once there is a demo to have read."""
    _, body = get(server, "/step/clip")
    assert "1 · Try it" in body and "Run the demo" in body
    assert "Run it on everything" not in body
    assert "2 · Read what came out" not in body


def test_the_topics_page_opens_on_a_list_and_names_the_others(server):
    _, body = get(server, "/step/topics")
    assert "1 · Try it" in body                  # it opens on a list, not on a chooser
    assert "collection" in body and "filter" in body


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


def test_only_this_mac_can_reach_the_app(server):
    """Without a host check, a page elsewhere could point a name at 127.0.0.1 and read the
    review pages — which are the transcripts."""
    request = urllib.request.Request(f"http://127.0.0.1:{server}/api/health",
                                     headers={"Host": "somewhere-else.example"})
    try:
        urllib.request.urlopen(request, timeout=10)
        pytest.fail("a request for another host was served")
    except urllib.error.HTTPError as e:
        assert e.code == 400


def test_pages_refuse_to_be_framed(server):
    """A hidden frame over a decoy page could otherwise collect the clicks that approve a run."""
    with urllib.request.urlopen(f"http://127.0.0.1:{server}/", timeout=10) as response:
        assert response.headers["Content-Security-Policy"] == "frame-ancestors 'none'"


def test_a_second_start_hands_over_to_the_running_one(server, workspace, fake_home):
    """Double-clicking the launcher again must not start a second server."""
    result = subprocess.run(
        [sys.executable, "-m", "transcript_toolkit.cli", "app", "--no-browser",
         "--port", str(server), "--project", str(workspace.root)],
        capture_output=True, text=True, timeout=60, env=app_env(fake_home))
    assert result.returncode == 0
    assert "already running" in result.stdout
    assert get(server, "/api/health")[0] == 200          # still the original


def test_a_port_someone_else_holds_is_reported_with_the_way_out(workspace, fake_home):
    with socket.socket() as squatter:
        squatter.bind(("127.0.0.1", 0))
        squatter.listen(1)
        port = squatter.getsockname()[1]
        result = subprocess.run(
            [sys.executable, "-m", "transcript_toolkit.cli", "app", "--no-browser",
             "--port", str(port), "--project", str(workspace.root)],
            capture_output=True, text=True, timeout=60, env=app_env(fake_home))
    assert result.returncode == 2
    assert "already used by another program" in result.stderr
    assert f"--port {port + 1}" in result.stderr


def test_home_offers_browsing_instead_of_typing_a_path(server):
    """Nobody should have to know what a path is to open their own project."""
    _, body = get(server, "/")
    assert "Browse" in body
    assert "Project name" in body and "Its folder will be:" in body


def test_the_workspace_page_lists_the_transcripts_and_their_state(server, workspace):
    _, body = get(server, "/workspace")
    for path in workspace.data_dir.glob("*.docx"):
        assert path.name in body
    assert "Drop .docx files here" in body          # the instruction stays
    assert "imported" in body


def test_the_demo_interviews_are_chosen_on_the_workspace_page(server):
    _, body = get(server, "/workspace")
    assert "Pick the sample of interviews for demos" in body
    assert "Draw them at random" in body and "Choose the interviews myself" in body
    # how many comes before the choice of how to fill it
    assert body.index("How many interviews") < body.index("Draw them at random")
    assert "Between 3 and" in body                      # and a demo has a floor


def test_the_terminal_viewer_is_its_own_section_at_the_foot_of_the_page(server):
    _, body = get(server, "/step/clip")
    assert "Terminal Viewer" in body
    assert "window onto a command-line tool" in body
    # and it is the last thing on the page, below everything that starts a command
    assert body.index("1 · Try it") < body.index("Terminal Viewer")


def test_chunking_is_out_of_the_way_among_the_extras(server):
    _, body = get(server, "/step/clip")
    assert "Extra tools" in body
    assert "How interviews will be split up" in body
    assert "far longer than a model can read in one go" in body      # the `i` explanation


def test_a_step_page_reads_in_the_order_the_work_happens(server):
    """The complaint this shape answers: the state of a run appeared at the very bottom, below
    the review links and every option, so it did not look like it belonged to the button that
    had been pressed. Now the buttons come first, then their state, then the things that change
    the step, then the terminal."""
    _, body = get(server, "/step/clip")
    order = ["1 · Try it", "Settings for this step", "Extra tools", "Terminal Viewer"]
    positions = [body.index(text) for text in order]
    assert positions == sorted(positions), order


def test_a_step_page_carries_its_own_settings_and_its_prompt(server):
    """Settings that belong to one step live on that step's page, and so does the prompt — which
    had no way in at all before."""
    _, body = get(server, "/step/clip")
    assert "Settings for this step" in body and "The prompt for this step" in body
    assert "Thinking effort" in body
    # the explanation is config.yaml's own comment, not a second copy written into the app
    assert "How much thinking the model does before it answers" in body


def test_the_settings_drawer_holds_only_what_belongs_to_the_whole_project(server):
    _, body = get(server, "/step/clip")
    assert "This project" in body and "Quit the toolkit" in body
    assert "Thinking effort" in body                     # on the page, from the step
    assert body.count("Thinking effort") == 1            # and not also in the drawer


def test_a_topic_list_can_be_written_in_the_app(server):
    _, body = get(server, "/step/topics?add=1")
    assert "Write one here" in body and "Upload a spreadsheet" in body
    assert "description" in body


def test_the_running_version_is_on_screen(server):
    """The first question about any odd behaviour is which version is running — and after a
    reinstall from a branch, that is exactly what nobody can tell by looking."""
    _, body = get(server, "/")
    assert __version__ in body


def test_the_header_shows_the_project_name_and_the_way_back_to_the_others(server, workspace):
    _, body = get(server, "/workspace")
    assert workspace.root.name in body            # the folder
    assert "/app-icon.png" in body                # the real icon, not a placeholder glyph
    assert "All your projects" in body            # what clicking it does
    assert "Rename the project" in body           # and a way to fix a name you did not choose


def test_the_header_icon_is_served_from_the_package(server):
    status, _ = get(server, "/app-icon.png")
    assert status == 200


def test_the_version_check_does_not_run_on_every_page(server, monkeypatch):
    """The drawer is built on every page and the check calls GitHub. Doing it per page load
    would put a network round trip behind every click."""
    _, body = get(server, "/step/clip")
    assert "Install the latest version" in body      # the drawer is there
    assert "checking for a newer version" not in body       # but it has not gone looking


def test_the_workspace_page_reports_what_the_project_has_cost(server):
    """The question somebody asks before starting the next expensive thing, on the page that is
    about the project as a whole."""
    _, body = get(server, "/workspace")
    assert "Project cost report" in body
    assert "billed in this project so far" in body
    assert "8.00 billed" not in body          # the figure is in its own label
    assert "&#36;8.00" in body                # 1M in + 100k out on gpt-5.6-sol
    assert "Clip" in body


def test_a_step_page_says_what_that_step_has_cost(server):
    _, body = get(server, "/step/clip")
    assert "This step has cost" in body and "8.00 so far (1 call)" in body


def test_topic_lists_get_a_tab_each_and_a_way_to_add_another(server):
    """Two lists are two pieces of work — separate demos, separate prompts, separate settings —
    so the page has to keep them apart rather than quietly using the first."""
    _, body = get(server, "/step/topics?set=filter")
    assert "collection" in body and "filter" in body
    assert "Add a topic list" in body
    assert "Change how 'filter' is tagged" in body


def test_a_topic_list_can_be_added_when_there_are_already_some(server):
    """Before, the editor only appeared when a project had no lists at all, so a second one could
    only arrive as an upload."""
    _, body = get(server, "/step/topics?add=1")
    assert "A new topic list" in body
    assert "Write one here" in body and "Upload a spreadsheet" in body


def test_a_shared_prompt_says_that_it_is_shared(server):
    _, body = get(server, "/step/topics?set=collection")
    assert "shared by every topic list" in body
    assert "Give 'collection' its own prompt" in body


def test_house_rules_can_be_written_rather_than_only_chosen(server):
    _, body = get(server, "/step/label")
    assert "House rules added to the prompt" in body
    assert "Write new house rules" in body


def test_the_settings_url_still_works_and_opens_the_panel(server):
    status, body = get(server, "/settings")
    assert status == 200
    assert "Settings are in the panel on the right" in body


def test_rolling_up_reads_as_compare_then_choose_then_apply(server):
    """Deciding when a topic becomes an interview's tag used to happen inside the rollup, from a
    number nobody had been shown the consequences of. Now the page asks for it in the order the
    decision is made, and the comparison that informs it comes first."""
    _, body = get(server, "/step/topics?set=collection")
    order = ["4 · Compare how tags are decided", "5 · Choose how tags are decided",
             "6 · Roll up to interview tags"]
    positions = [body.index(text) for text in order]
    assert positions == sorted(positions), order
    assert "What to compare" in body and "Bands to compare" in body


def test_the_rollup_rule_is_two_numbers_and_the_method_is_folded_away(server):
    """Most projects should never change the method, so the page asks for the two things they
    should tune and keeps the rest out of the way."""
    _, body = get(server, "/step/topics?set=collection")
    assert "Bands" in body and "Use a different method" in body
    assert "Bars: 10%, 15%, 20%, 25%, 30%" in body          # what those numbers come to
    assert "A lower bar for rarer topics — recommended" in body
    # and it is not also sitting in the step's settings, where it was before
    settings_at = body.index("Settings for this step")
    assert body.index("Use a different method") < settings_at


def test_the_state_of_a_run_sits_under_the_thing_that_starts_it(server):
    """Not at a fixed place on the page: on Topics the one panel used to land between step 3 and
    step 4, describing neither."""
    _, body = get(server, "/step/topics?set=collection")
    # the demo's own state is above the moves that follow tagging, not below them
    assert body.index("1 · Try it") < body.index("4 · Compare how tags are decided")
    assert body.index("Terminal Viewer") > body.index("6 · Roll up to interview tags")


def test_locations_rolls_up_the_same_way(server):
    _, body = get(server, "/step/locations")
    order = ["4 · Expand regions into countries", "5 · Compare how tags are decided",
             "6 · Choose how tags are decided", "7 · Roll up to interview places"]
    positions = [body.index(text) for text in order]
    assert positions == sorted(positions), order
