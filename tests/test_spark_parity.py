"""Spark pipeline must reproduce the pure-Python Stage 1 pipeline exactly."""

import json
import os
from pathlib import Path

import pytest

pyspark = pytest.importorskip("pyspark")

from finsight.ingestion.finqa import transform_record
from finsight.spark import finqa_silver as fs

FIXTURES = Path(__file__).parent / "fixtures" / "finqa_raw"


@pytest.fixture(scope="module")
def spark():
    from pyspark.sql import SparkSession

    src = str(Path(__file__).parents[1] / "src")
    os.environ["PYTHONPATH"] = src + os.pathsep + os.environ.get("PYTHONPATH", "")
    s = (SparkSession.builder.master("local[2]").config("spark.ui.enabled", "false")
         .config("spark.executorEnv.PYTHONPATH", src).getOrCreate())
    yield s
    s.stop()


@pytest.fixture(scope="module")
def silver(spark):
    bronze = fs.read_bronze(spark, str(FIXTURES), "c0ffee", "test-run").cache()
    return bronze, fs.documents(bronze), fs.evidence_units(bronze), fs.questions(bronze)


def _reference():
    docs, units, qs = {}, {}, {}
    for f in FIXTURES.glob("*.json"):
        for rec in json.loads(f.read_text()):
            d, us, q = transform_record(rec, f.stem)
            docs[d.doc_id] = d.model_dump(mode="json")
            for u in us:
                units.setdefault(u.unit_id, u.model_dump(mode="json"))
            qs[q.question_id] = q.model_dump(mode="json")
    return docs, units, qs


def _assert_same(ref, rows, key, cols):
    got = {r[key]: r.asDict() for r in rows}
    assert got.keys() == ref.keys()
    for k, r in ref.items():
        for c in cols:
            a, b = r[c], got[k][c]
            if isinstance(a, list):
                a, b = sorted(a), sorted(b or [])
            assert a == b, f"{k}.{c}: python={a!r} spark={b!r}"


def test_parity(silver):
    _, docs, units, qs = silver
    ref_d, ref_u, ref_q = _reference()
    _assert_same(ref_d, docs.collect(), "doc_id",
                 ["ticker", "fiscal_year", "page", "split", "n_text_units", "n_table_rows"])
    _assert_same(ref_u, units.collect(), "unit_id",
                 ["doc_id", "kind", "position", "text", "row_label", "header", "cells"])
    _assert_same(ref_q, qs.collect(), "question_id",
                 ["doc_id", "split", "question", "gold_answer_text", "gold_program", "gold_exe_ans",
                  "gold_unit_ids", "evidence_type", "n_steps", "executor_value",
                  "executor_matches_gold", "label_status"])


def test_quality_checks_pass_and_report(silver):
    bronze, docs, _, qs = silver
    m = fs.quality_checks(bronze, docs, qs)
    assert m["executor_agreement"] == 1.0 and not m["failures"]


def test_quality_checks_fail_on_split_leak(spark, silver):
    from pyspark.sql import functions as F
    bronze, docs, _, _ = silver
    leaked = bronze.unionByName(bronze.limit(1).withColumn("split", F.lit("dev"))
                                .withColumn("id", F.concat("id", F.lit("-dup"))))
    with pytest.raises(ValueError, match="more than one split"):
        fs.quality_checks(leaked, docs, fs.questions(leaked))
