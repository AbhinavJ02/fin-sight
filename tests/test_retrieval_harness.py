import json
from pathlib import Path

import pytest

from finsight.eval.retrieval import HEADLINE, build_run, evaluate, group_units
from finsight.ingestion.finqa import transform_record
from finsight.retrieval.bm25 import BM25Retriever

FIXTURES = Path(__file__).parent / "fixtures" / "finqa_raw"


def _fixture_silver():
    questions, units = [], []
    for rec in json.loads((FIXTURES / "test.json").read_text()):
        _, us, q = transform_record(rec, "test")
        questions.append(q)
        units.extend(us)
    return questions, group_units({u.unit_id: u for u in units}.values())


class Oracle:
    """Puts gold units first. Must score 1.0 on everything that is achievable."""

    name = "oracle"

    def __init__(self, questions):
        self.gold = {q.question: set(q.gold_unit_ids) for q in questions}

    def params(self):
        return {}

    def rank(self, question, candidates):
        g = self.gold[question]
        return sorted((u.unit_id for u in candidates), key=lambda uid: uid not in g)


class Truncating:
    name = "broken"

    def params(self):
        return {}

    def rank(self, question, candidates):
        return [candidates[0].unit_id]


def test_oracle_scores_perfectly():
    questions, by_doc = _fixture_silver()
    results = evaluate(Oracle(questions), questions, by_doc, "r1")
    assert len(results) == len(questions)
    for r in results:
        assert r.metrics["rr"] == 1.0 and r.metrics["ndcg@10"] == pytest.approx(1.0)
        assert r.gold_ranks == list(range(1, r.n_gold + 1))


def test_bm25_run_summary_has_ci_and_random_baseline():
    questions, by_doc = _fixture_silver()
    retriever = BM25Retriever()
    results = evaluate(retriever, questions, by_doc, "r2")
    run = build_run("r2", "test", retriever, results, {"finqa_questions": 0}, Path("."))
    breakdown = json.loads(run.breakdown_json)
    for m in HEADLINE:
        lo, hi = breakdown["overall_ci95"][m]
        assert lo <= run.summary[m] <= hi
        assert 0.0 <= run.random_summary[m] <= 1.0
    assert {"evidence_type", "n_gold", "label_status"} <= set(breakdown)
    assert json.loads(run.params_json)["idf_scope"] == "page"


def test_partial_ranking_is_rejected():
    questions, by_doc = _fixture_silver()
    with pytest.raises(ValueError, match="full ranking"):
        evaluate(Truncating(), questions, by_doc, "r3")
