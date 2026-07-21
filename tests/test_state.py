import pytest

from transcript_toolkit.errors import ToolkitError
from transcript_toolkit.project import init_project
from transcript_toolkit.state import (
    check_demo_gate,
    demo_status,
    load_state,
    record_demo,
    record_full,
)


@pytest.fixture
def project(tmp_path):
    return init_project(str(tmp_path / "ws"))


def test_gate_refuses_without_demo(project):
    assert demo_status(project, "clip", "fp1") == "none"
    with pytest.raises(ToolkitError, match="No demo run"):
        check_demo_gate(project, "clip", "fp1", demo_command="toolkit clip --demo")


def test_gate_passes_after_matching_demo(project):
    record_demo(project, "clip", "fp1", units=["a", "b"], diag="diags/clip/demo.md")
    assert demo_status(project, "clip", "fp1") == "current"
    check_demo_gate(project, "clip", "fp1", demo_command="toolkit clip --demo")  # no raise


def test_gate_stale_after_fingerprint_change(project):
    record_demo(project, "clip", "fp1", units=["a"], diag="d.md")
    assert demo_status(project, "clip", "fp2") == "stale"
    with pytest.raises(ToolkitError, match="stale"):
        check_demo_gate(project, "clip", "fp2", demo_command="toolkit clip --demo")


def test_gate_skip_bypasses(project):
    check_demo_gate(project, "clip", "fp1", demo_command="x", skip=True)  # no raise


def test_records_persist_per_step_key(project):
    record_demo(project, "topics:main", "fpA", units=["c1"], diag="d1.md")
    record_full(project, "topics:main", "fpA", model="gpt-5.4-mini", n_units=100)
    record_demo(project, "topics:alt", "fpB", units=["c2"], diag="d2.md")
    state = load_state(project)
    assert state["steps"]["topics:main"]["full"]["n_units"] == 100
    assert state["steps"]["topics:alt"]["demo"]["fingerprint"] == "fpB"
    assert "full" not in state["steps"]["topics:alt"]
