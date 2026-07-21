"""`toolkit topics thresholds` — decision aid for the clip->interview rollup thresholds.

Prints a flat-threshold sweep (how tagging behaves as the bar moves 10..40%) and renders ONE
comparison figure — flat 30% baseline vs the configured rollup scheme, interviews reached per
topic — into diags/topics/plots/. Reads the clip-level deliverable only; never touches the
rollup deliverables. Use it to pick threshold_pct / the binned bar list in config.yaml.
"""
from __future__ import annotations

from ...core.config import load_step_config, require
from ...core.thresholds import flat_thresholds
from ...project import Project
from .rollup import pooled_shares, scheme_thresholds
from .taxonomy import load_topic_set, resolve_set

STEP = "topics"
SWEEP = [10, 15, 20, 25, 30, 35, 40]


def run_topics_thresholds(project: Project, set_name: str | None = None) -> None:
    cfg = load_step_config(project, STEP)
    require(cfg, ["score_values"], STEP)
    tset = load_topic_set(project, cfg, set_name)
    sset = tset.name
    _, entry = resolve_set(cfg, sset)

    _, pct, freq, n_clips, _ = pooled_shares(project, cfg, tset)
    n_int, n_top = pct.shape

    print(f"Flat-threshold sweep · set '{sset}' · {n_int} interviews × {n_top} topics")
    print(f"  {'bar':>6}  {'topics reached':>14}  {'untagged interviews':>19}  {'total tags':>10}")
    for p in SWEEP:
        tagged = pct.ge(float(p))
        reach = tagged.sum(axis=0)
        tpi = tagged.sum(axis=1)
        print(f"  >={p:>3}%  {int((reach > 0).sum()):>7} of {n_top:<3} "
              f"{int((tpi == 0).sum()):>19}  {int(tagged.values.sum()):>10}")

    try:
        import matplotlib
    except ImportError:
        print("\nmatplotlib not installed; skipping the flat-vs-configured comparison figure.")
        return
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    thr_cfg, scheme_desc = scheme_thresholds(entry.get("rollup"), freq, sset)
    schemes = {"flat 30%": flat_thresholds(freq, 30.0),
               f"configured: {scheme_desc}": thr_cfg}
    order = sorted(tset.ids, key=lambda t: (int(freq[t]), t))    # ascending freq, bottom-up
    reach = {name: pct.ge(thr, axis=1).sum(axis=0) for name, thr in schemes.items()}
    y = np.arange(len(order))
    xmax = max(3, int(max(r.max() for r in reach.values())) + 1)

    fig, axes = plt.subplots(1, 2, figsize=(11, max(4.0, 0.34 * len(order) + 1.5)), sharey=True)
    for ax, (name, thr) in zip(axes, schemes.items()):
        r = reach[name]
        ax.barh(y, [int(r[t]) for t in order], color="#4292c6", edgecolor="white")
        for t, yy in zip(order, y):
            ax.text(int(r[t]) + 0.05, yy, f"{int(r[t])} · bar {thr[t]:g}%", va="center", fontsize=7)
        ax.set_title(f"{name}\n{int((r > 0).sum())}/{len(order)} topics reached · "
                     f"total tags {int(r.sum())}", fontsize=10)
        ax.set_xlabel("# interviews tagged", fontsize=9)
        ax.set_xlim(0, xmax)
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].set_yticks(y)
    axes[0].set_yticklabels([f"{t}  ({int(freq[t])})" for t in order], fontsize=8)
    fig.suptitle(f"topics · set '{sset}' · interviews reached per topic (of {n_int}) — "
                 f"topics sorted by clip-frequency (n)", fontsize=11, weight="bold")

    out = project.diags_dir / "topics" / "plots" / f"{sset}_thresholds.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"\nwrote {out}")
