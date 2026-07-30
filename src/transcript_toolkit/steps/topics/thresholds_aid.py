"""`toolkit topics thresholds` — the decision aid that comes BEFORE `toolkit topics rollup`.

Rolling up is the cheap, deterministic part; deciding when a topic is enough of an interview to
be one of its tags is the judgement. This works every candidate rule out against the tags that
are already there and writes a review page comparing them — a panel per method, the recommended
one open — so the rule is chosen by looking at what it would do rather than by picking numbers.

Reads the clip-level deliverable only. It writes no deliverables and makes no API calls, so it
can be run as often as it takes.
"""
from __future__ import annotations

from ...core import thresholdreview, thresholds
from ...core.config import load_step_config, require
from ...project import Project
from .rollup import pooled_shares
from .taxonomy import load_topic_set

STEP = "topics"

LEAD = ("Every rule below tags an interview with a topic once enough of that interview's clips "
        "were assigned to it. They differ in how 'enough' is decided, and the difference is "
        "largest for the topics that come up least. Pick the one whose picture you would be "
        "happy to publish, then set it under 'Choose how tags are decided' and roll up.")


def run_topics_thresholds(project: Project, set_name: str | None = None,
                          bins: list[int] | None = None,
                          ranges: list[tuple[float, float]] | None = None,
                          flat: list[float] | None = None) -> None:
    cfg = load_step_config(project, STEP)
    require(cfg, ["score_values"], STEP)
    tset = load_topic_set(project, cfg, set_name)
    sset, current = tset.name, tset.rollup

    _, pct, freq, _, _ = pooled_shares(project, cfg, tset)
    n_int, n_top = pct.shape

    def evaluate(rollup: thresholds.Rollup):
        """What this rule would tag: the bar per topic, the interviews each topic would reach,
        and how many interviews would come out with no topic at all."""
        thr = rollup.thresholds(freq)
        tagged = pct.ge(thr, axis=1)
        return thr, tagged.sum(axis=0), int((tagged.sum(axis=1) == 0).sum())

    options = thresholds.compare_options(cfg)
    for name, given in (("bins", bins), ("ranges", ranges), ("flat", flat)):
        if given:
            options[name] = given

    panels = thresholdreview.build(options, current, evaluate, thresholds.TOPICS)
    order = sorted(tset.ids, key=lambda t: (int(freq[t]), t))     # ascending: bottom-up on barh

    print(f"Comparing rollup rules · set '{sset}' · {n_int} interviews × {n_top} topics")
    print(f"What you have now: {current.describe()}")
    thresholdreview.report(panels, n_int)

    out = thresholdreview.write(
        project.diags_dir / STEP, sset,
        title=f"Topics · {sset} · choosing how tags are decided",
        subtitle=f"{n_top} topics · {n_int} interviews · what you have now: {current.describe()}",
        panels=panels, order=order, freq=freq, n_int=n_int, lead=LEAD)
    print(f"\nWrote {out}")
