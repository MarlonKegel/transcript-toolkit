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


def sample_keys(keys: list[str], n: int, seed: int) -> list[str]:
    """Up to n keys, reproducibly (seeded); all keys if n >= len(keys)."""
    ks = sorted(keys)
    if n >= len(ks):
        return ks
    return sorted(random.Random(seed).sample(ks, n))


def draw_interview_sample(project: Project, n: int = DEFAULT_N, seed: int = 0,
                          explicit: list[str] | None = None) -> list[str]:
    available = sorted(load_paragraphs(project)["interview_id"].unique())
    if explicit:
        unknown = [i for i in explicit if i not in available]
        if unknown:
            raise ToolkitError(f"Unknown interview id(s): {', '.join(unknown)}. "
                               f"Available: {', '.join(available)}")
        sample = sorted(explicit)
    else:
        sample = sample_keys(available, n, seed)
    project.demo_sample_path.parent.mkdir(parents=True, exist_ok=True)
    project.demo_sample_path.write_text("\n".join(sample) + "\n")
    return sample


def load_interview_sample(project: Project) -> list[str]:
    if not project.demo_sample_path.exists():
        raise ToolkitError("No demo sample drawn yet. Run `toolkit sample` first "
                           "(picks the interviews demo runs use).")
    return [line for line in project.demo_sample_path.read_text().splitlines() if line.strip()]
