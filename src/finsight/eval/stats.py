"""Bootstrap confidence intervals over questions.

Questions are the resampling unit. With ~900-1,100 questions per split, a few points of
difference between retrievers can be noise; comparisons use the paired bootstrap so that
per-question difficulty cancels out.
"""

from __future__ import annotations

import random
from collections.abc import Sequence

N_BOOT = 1000
SEED = 0


def _percentile(sorted_xs: list[float], q: float) -> float:
    return sorted_xs[min(len(sorted_xs) - 1, max(0, round(q * (len(sorted_xs) - 1))))]


def bootstrap_ci(values: Sequence[float], n_boot: int = N_BOOT, seed: int = SEED,
                 alpha: float = 0.05) -> tuple[float, float, float]:
    """(mean, low, high) percentile interval for the mean."""
    n = len(values)
    rng = random.Random(seed)
    means = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_boot))
    return sum(values) / n, _percentile(means, alpha / 2), _percentile(means, 1 - alpha / 2)


def paired_bootstrap(a: Sequence[float], b: Sequence[float], n_boot: int = N_BOOT,
                     seed: int = SEED, alpha: float = 0.05) -> tuple[float, float, float]:
    """(mean of a - b, low, high) over the same questions in the same order."""
    if len(a) != len(b):
        raise ValueError("paired bootstrap needs equal-length inputs")
    return bootstrap_ci([x - y for x, y in zip(a, b, strict=True)], n_boot, seed, alpha)
