"""Demo samples.

The interview-level demo sample (used by clip/label demos) is drawn once with `toolkit sample`
and persisted to .toolkit/demo_sample.txt so the SAME handful of interviews flows through both
stages. Clip-level demo samples (topics/locations) and summarize's interview sample are drawn
per run from a seed instead — reproducible without a file.
"""
from __future__ import annotations

import random

from ..errors import ToolkitError
from ..project import Project
from .tables import load_paragraphs

DEFAULT_N = 5
# A demo has to be big enough to judge a prompt by and small enough to re-run without thinking
# about the cost. `toolkit sample` holds both ends (cli.cmd_sample) and the app offers only sizes
# inside them, so the two agree about what a demo is.
MIN_N = 3
MAX_N = 10


def check_size(n: int, available: int) -> None:
    """Refuse a demo sample too small to read anything into, or too big to be a demo."""
    floor = min(MIN_N, available)
    if n < floor:
        raise ToolkitError(
            f"A demo runs on at least {floor} interview{'s' if floor != 1 else ''}; "
            f"{n} would not show enough to judge the results by.")
    if n > MAX_N:
        raise ToolkitError(
            f"A demo runs on at most {MAX_N} interviews — every step's demo is run several "
            f"times over, so a bigger one costs more than it tells you. To process a chosen few "
            f"for real, use `toolkit clip --interview <id>` instead.")


def sample_keys(keys: list[str], n: int, seed: int) -> list[str]:
    """Up to n keys, reproducibly (seeded); all keys if n >= len(keys)."""
    ks = sorted(keys)
    if n >= len(ks):
        return ks
    return sorted(random.Random(seed).sample(ks, n))


def draw_interview_sample(project: Project, n: int | None = None, seed: int = 0,
                          explicit: list[str] | None = None) -> list[str]:
    """Choose the interviews demo runs use, and remember them.

    `explicit` interviews are always in the sample. If `n` asks for more than were named, the
    rest are drawn at random from the interviews that were not — so "these two plus three
    others" is one call, not two. Naming interviews without an `n` gives exactly those.
    """
    available = sorted(load_paragraphs(project)["interview_id"].unique())
    if explicit:
        unknown = [i for i in explicit if i not in available]
        if unknown:
            raise ToolkitError(f"Unknown interview id(s): {', '.join(unknown)}. "
                               f"Available: {', '.join(available)}")
        sample = sorted(set(explicit))
        if n is not None and n > len(sample):
            rest = [i for i in available if i not in sample]
            sample = sorted(sample + sample_keys(rest, n - len(sample), seed))
    else:
        sample = sample_keys(available, DEFAULT_N if n is None else n, seed)
    project.demo_sample_path.parent.mkdir(parents=True, exist_ok=True)
    project.demo_sample_path.write_text("\n".join(sample) + "\n")
    return sample


def sample_clips_spread(clips_df, n: int, seed: int) -> list[str]:
    """~n clip_ids spread across interviews: round-robin over a shuffled clip order within
    each interview, one clip per interview per pass. Fully reproducible via `seed` (a single
    seeded RNG drives all shuffles; interviews visited in deterministic order)."""
    rng = random.Random(seed)
    per_interview: dict[str, list[str]] = {}
    for iid in sorted(clips_df["interview_id"].unique()):
        ids = (clips_df[clips_df["interview_id"] == iid]
               .sort_values("start_paragraph_idx")["clip_id"].tolist())
        rng.shuffle(ids)
        per_interview[iid] = ids
    order = sorted(per_interview)
    rng.shuffle(order)
    picked: list[str] = []
    pass_idx = 0
    while len(picked) < n and any(len(v) > pass_idx for v in per_interview.values()):
        for iid in order:
            if pass_idx < len(per_interview[iid]):
                picked.append(per_interview[iid][pass_idx])
                if len(picked) >= n:
                    break
        pass_idx += 1
    return picked


def load_interview_sample(project: Project) -> list[str]:
    if not project.demo_sample_path.exists():
        raise ToolkitError("No demo sample drawn yet. Run `toolkit sample` first "
                           "(picks the interviews demo runs use).")
    return [line for line in project.demo_sample_path.read_text().splitlines() if line.strip()]
