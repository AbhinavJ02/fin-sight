"""Ranking metrics for in-page evidence retrieval.

Every metric is computed from the 1-based ranks of the gold units in a full ranking of
the page's candidates. Relevance is binary: a unit is either gold or not.

`expected_random` gives the exact expectation of each metric under a uniformly random
ranking of the same page. In-page candidate sets are small (median 30 units on test),
so Recall@10 alone is easy to misread; every reported number sits next to this baseline.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from math import comb

KS = (1, 3, 5, 10)


def gold_ranks(ranked_ids: Sequence[str], gold_ids: Sequence[str]) -> list[int]:
    pos = {uid: i + 1 for i, uid in enumerate(ranked_ids)}
    missing = [g for g in gold_ids if g not in pos]
    if missing:
        raise ValueError(f"gold units not among candidates: {missing}")
    return sorted(pos[g] for g in set(gold_ids))


def recall_at_k(ranks: Sequence[int], k: int) -> float:
    """Fraction of gold units in the top k."""
    return sum(r <= k for r in ranks) / len(ranks)


def all_gold_at_k(ranks: Sequence[int], k: int) -> float:
    """1.0 if every gold unit is in the top k. Multi-hop programs need all of them."""
    return float(max(ranks) <= k)


def reciprocal_rank(ranks: Sequence[int]) -> float:
    return 1.0 / min(ranks)


def _dcg_weight(rank: int) -> float:
    return 1.0 / math.log2(rank + 1)


def ndcg_at_k(ranks: Sequence[int], k: int) -> float:
    dcg = sum(_dcg_weight(r) for r in ranks if r <= k)
    idcg = sum(_dcg_weight(i) for i in range(1, min(len(ranks), k) + 1))
    return dcg / idcg


def compute_all(ranks: Sequence[int]) -> dict[str, float]:
    out = {"rr": reciprocal_rank(ranks)}
    for k in KS:
        out[f"recall@{k}"] = recall_at_k(ranks, k)
        out[f"all_gold@{k}"] = all_gold_at_k(ranks, k)
        out[f"ndcg@{k}"] = ndcg_at_k(ranks, k)
    return out


def expected_random(n: int, g: int) -> dict[str, float]:
    """Exact expected metrics when g gold units are placed uniformly among n positions."""
    if not 1 <= g <= n:
        raise ValueError(f"need 1 <= g <= n, got g={g}, n={n}")
    total = comb(n, g)
    # P(best gold rank == r) = C(n - r, g - 1) / C(n, g)
    rr = sum(comb(n - r, g - 1) / r for r in range(1, n - g + 2)) / total
    idcg_all = [sum(_dcg_weight(i) for i in range(1, min(g, k) + 1)) for k in KS]
    out = {"rr": rr}
    for k, idcg in zip(KS, idcg_all, strict=True):
        kk = min(k, n)
        out[f"recall@{k}"] = kk / n
        out[f"all_gold@{k}"] = comb(kk, g) / total  # comb is 0 when kk < g
        # Each gold unit lands on each position with probability 1/n (linearity).
        out[f"ndcg@{k}"] = g * sum(_dcg_weight(i) for i in range(1, kk + 1)) / n / idcg
    return out
