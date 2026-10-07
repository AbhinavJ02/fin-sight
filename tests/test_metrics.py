import itertools
import math

import pytest

from finsight.eval.metrics import (
    KS,
    all_gold_at_k,
    compute_all,
    expected_random,
    gold_ranks,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
)
from finsight.eval.stats import bootstrap_ci, paired_bootstrap


def test_gold_ranks_are_one_based_and_sorted():
    assert gold_ranks(["a", "b", "c", "d"], ["d", "b"]) == [2, 4]
    with pytest.raises(ValueError):
        gold_ranks(["a", "b"], ["z"])


def test_hand_computed_values():
    ranks = [2, 4]  # two gold units at positions 2 and 4
    assert recall_at_k(ranks, 1) == 0.0
    assert recall_at_k(ranks, 3) == 0.5
    assert recall_at_k(ranks, 5) == 1.0
    assert all_gold_at_k(ranks, 3) == 0.0
    assert all_gold_at_k(ranks, 4) == 1.0
    assert reciprocal_rank(ranks) == 0.5
    # DCG@5 = 1/log2(3) + 1/log2(5); IDCG@5 = 1/log2(2) + 1/log2(3)
    expected = (1 / math.log2(3) + 1 / math.log2(5)) / (1 + 1 / math.log2(3))
    assert ndcg_at_k(ranks, 5) == pytest.approx(expected)


def test_perfect_ranking_scores_one():
    m = compute_all([1, 2, 3])
    assert m["rr"] == 1.0
    assert all(m[f"ndcg@{k}"] == pytest.approx(1.0) for k in KS)
    assert m["recall@3"] == m["all_gold@3"] == 1.0
    assert m["recall@1"] == pytest.approx(1 / 3)


@pytest.mark.parametrize("n,g", [(1, 1), (5, 1), (5, 2), (6, 3), (7, 7), (12, 2)])
def test_expected_random_matches_enumeration(n, g):
    """Every placement of g gold units among n positions is equally likely."""
    placements = list(itertools.combinations(range(1, n + 1), g))
    brute = {m: 0.0 for m in compute_all(list(placements[0]))}
    for ranks in placements:
        for m, v in compute_all(list(ranks)).items():
            brute[m] += v / len(placements)
    exact = expected_random(n, g)
    for m, v in brute.items():
        assert exact[m] == pytest.approx(v, abs=1e-12), m


def test_bootstrap_is_reproducible_and_brackets_mean():
    vals = [0.0, 1.0] * 50
    mean, lo, hi = bootstrap_ci(vals)
    assert mean == 0.5 and lo < 0.5 < hi
    assert bootstrap_ci(vals) == (mean, lo, hi)
    d, dlo, dhi = paired_bootstrap([1.0] * 10, [0.0] * 10)
    assert (d, dlo, dhi) == (1.0, 1.0, 1.0)
