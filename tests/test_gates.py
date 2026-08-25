"""Which buttons are live, and when.

A button the app greys out is a statement that there is nothing to work from yet. Getting that
wrong in one direction is a nuisance (a live button that fails in the terminal); getting it
wrong in the other is a dead end — the whole rest of a step unreachable, with nothing on screen
saying why. That happened: every move after `locations tag` was gated on a file `locations map`
writes, so step 4 waited for its own output and steps 4, 5 and 6 were greyed out for ever.

So these tests are about the gate itself rather than about locations. The first walks a project
through the pipeline and pins exactly which moves open at each point. The second states the
invariant the bug broke, for every step there is and every step there will be.
"""
import pytest

from transcript_toolkit.app import content
from transcript_toolkit.project import init_project
from transcript_toolkit.steps import freshness as fresh

SET = "collection"


@pytest.fixture
def project(tmp_path):
    return init_project(str(tmp_path / "ws"))


def put(project, *relative_paths) -> None:
    """Put a step's output where it writes it. What is in it does not matter here — the gate is
    a question about whether the file is there, and nothing is read until a button is pressed."""
    for rel in relative_paths:
        path = project.outputs_dir / rel.format(set=SET)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")


def live(project) -> set[str]:
    """Every move the app would offer right now, as "step slug/action slug"."""
    have = content.available(project, SET)
    return {f"{step.slug}/{action.slug}" for step in content.STEPS
            for action in content.runnable(step)
            if not content.missing_for(action, have, SET)}


# Everything that never waits for anything: it explains what a run would do, or it goes and
# looks at the transcripts itself. These are live from the first moment and stay live.
ALWAYS = {"clip/preview", "locations/survey"}


def test_the_pipeline_opens_one_stage_at_a_time(project):
    """The gate matrix, in the order a project actually goes through it.

    Written as "what is newly clickable", because that is the question somebody has when they
    have just finished a step: what does this let me do that I could not do a minute ago?
    """
    assert live(project) == ALWAYS

    put(project, "clips/clips.parquet")
    assert live(project) == ALWAYS | {"clip/annotate", "label/preview"}

    put(project, "labels/labels.parquet")
    assert live(project) == ALWAYS | {"clip/annotate", "label/preview", "label/annotate"}
    after_labels = live(project)

    put(project, "summaries/summaries.parquet")
    assert live(project) == after_labels | {"summarize/annotate"}

    # Topics: tagging opens its own review pages and the comparison; the rollup waits for
    # nothing further, because it reads the same clip tags the comparison draws.
    put(project, "topics/{set}_clip_topics_wide.parquet")
    assert live(project) == after_labels | {"summarize/annotate", "topics/annotate",
                                            "topics/thresholds", "topics/rollup"}
    after_topics = live(project)

    # Locations: this is the one that was broken. Tagging opens the two moves that read the
    # tags — and NOT the two that read what `map` has yet to write.
    put(project, "locations/clip_locations.parquet")
    assert live(project) == after_topics | {"locations/map", "locations/annotate"}

    put(project, "locations/clip_countries.parquet")
    assert live(project) == after_topics | {"locations/map", "locations/annotate",
                                            "locations/thresholds", "locations/rollup"}


def test_a_tagged_collection_can_always_reach_the_rest_of_its_step(project):
    """The dead end itself, stated as the thing that must never be true again: after paying to
    tag a whole collection, there is a move to make."""
    put(project, "clips/clips.parquet", "locations/clip_locations.parquet")
    locations = content.BY_SLUG["locations"]
    have = content.available(project, SET)
    offered = [a.slug for a in content.runnable(locations)
               if not content.missing_for(a, have, SET)]
    assert "map" in offered, "nothing to press after tagging the whole collection"
    assert "annotate" in offered, "no way to rebuild the review page"


# --- the invariant --------------------------------------------------------------------------

def files_behind(name: str, set_name: str) -> tuple[str, ...]:
    """The files a `needs` name stands for — the same two tables `content.available` reads."""
    step_key, _, slug = name.partition(".")
    if slug:
        paths = fresh.DERIVED[(step_key, slug)][0]
    else:
        step = next(s for s in content.STEPS if s.deliverable == step_key.split(":")[0])
        paths = fresh.WRITES[step.key]
    return tuple(p.format(set=set_name) for p in paths)


def test_every_name_a_button_waits_for_is_a_real_file(project):
    """A typo in `needs` would silently disable a button for ever: the name it waits for can
    never appear, because nothing writes it."""
    for step in content.STEPS:
        for action in content.runnable(step):
            for need in action.needs:
                name = need.format(set=SET)
                assert files_behind(name, SET), f"{step.slug} {action.slug}: {name} names nothing"


def test_no_move_waits_for_its_own_output(project):
    """The bug, as a rule.

    `locations map` was gated on the deliverable called `locations`, and that name pointed at
    `clip_countries.parquet` — the file `map` itself writes. A move that waits for its own
    output can never be made. Stated over files rather than over names, because the names were
    not what was wrong: `map` and the gate agreed about the word and disagreed about the file.
    """
    for step in content.STEPS:
        for action in content.runnable(step):
            writes = fresh.DERIVED.get((step.key, action.slug))
            if writes is None:
                continue                    # writes no deliverable of its own; nothing to clash
            own = {p.format(set=SET) for p in writes[0]}
            waits_for = {f for need in action.needs
                         for f in files_behind(need.format(set=SET), SET)}
            clash = own & waits_for
            assert not clash, (f"{step.slug} {action.slug} waits for {sorted(clash)}, "
                               f"which is what it writes — it can never be run")


def test_the_gate_does_not_read_the_export_list(project):
    """`toolkit status`'s deliverable list answers "what would the spreadsheet include?", and
    for locations it answers with a file written a command after the tagging. It was the wrong
    list to gate buttons on; this pins the two apart so they cannot be conflated again."""
    from transcript_toolkit.steps.status import gather_status

    put(project, "clips/clips.parquet", "locations/clip_locations.parquet")
    assert "locations" not in gather_status(project)["deliverables"]     # export: nothing yet
    assert "locations" in content.available(project, SET)               # the gate: tags are there


def test_a_move_that_reads_an_earlier_move_says_where_to_go(project):
    """A greyed-out button has to point at the thing to press. For most of them that is another
    step; for the two that read what `map` wrote it is a numbered move higher up the same page,
    and sending somebody back to the step they just ran would be a dead end with directions."""
    from transcript_toolkit.app.pages.step import _nothing_to_read_yet

    locations = content.BY_SLUG["locations"]
    rollup = next(a for a in locations.sequels if a.slug == "rollup")
    said = _nothing_to_read_yet(locations, list(rollup.needs))
    assert "step 4" in said and "Expand regions into countries" in said
    assert "Run this step first" not in said

    clip = content.BY_SLUG["clip"]
    annotate = next(a for a in clip.extras if a.slug == "annotate")
    assert "Run this step first" in _nothing_to_read_yet(clip, list(annotate.needs))


def test_the_numbering_the_page_shows_is_the_numbering_it_names(project):
    """The tooltip says "step 4"; the page draws "4 · …". One source for both."""
    for step in content.STEPS:
        for i, action in enumerate(step.sequels, start=content.SEQUELS_START):
            assert content.sequel_number(step, action) == i
        for action in step.extras:
            assert content.sequel_number(step, action) is None      # extras are not numbered


def test_review_pages_are_declared_for_every_run_that_writes_one(project):
    """A demo whose page nothing links to is a demo that looks like it produced nothing — which
    is exactly how the locations demo read. Every step that writes a demo page under a name of
    its own has to declare that name."""
    demo_pages = {"clip": "index.html", "label": "index.html",
                  "summarize": "demo_summaries.html", "topics": "{set}_demo.html",
                  "locations": "demo.html"}
    for slug, filename in demo_pages.items():
        declared = {r.filename for r in content.BY_SLUG[slug].reviews}
        assert filename in declared, f"{slug}: nothing links to the page its demo writes"


def test_available_is_quiet_about_a_workspace_that_is_not_there(tmp_path):
    """Every page asks this while it renders. A project folder somebody has just thrown away in
    Finder must give an empty answer, not an exception on whichever page they click next."""
    import shutil

    project = init_project(str(tmp_path / "ws"))
    put(project, "clips/clips.parquet")
    assert content.available(project, SET) == {"clips"}
    shutil.rmtree(project.root)
    assert content.available(project, SET) == set()
