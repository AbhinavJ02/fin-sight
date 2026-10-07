"""FinQA bronze -> silver in PySpark.

Pure DataFrame-in / DataFrame-out functions so the same code runs in a Fabric
notebook and in local tests. Native Spark expressions are used wherever
possible; Python UDFs only where we must reuse the deterministic executor.
"""

from __future__ import annotations

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql import types as T

# Explicit schema: never rely on JSON inference in a pipeline. Inference turns
# gold_inds (variable keys) into a struct with hundreds of fields and makes
# exe_ans's type depend on which records happen to be sampled.
QA_SCHEMA = T.StructType([
    T.StructField("question", T.StringType()),
    T.StructField("answer", T.StringType()),
    T.StructField("program", T.StringType()),
    T.StructField("exe_ans", T.StringType()),          # numbers and "yes"/"no"
    T.StructField("gold_inds", T.MapType(T.StringType(), T.StringType())),
    T.StructField("steps", T.ArrayType(T.MapType(T.StringType(), T.StringType()))),
])

RAW_SCHEMA = T.StructType([
    T.StructField("id", T.StringType(), False),
    T.StructField("filename", T.StringType(), False),
    T.StructField("pre_text", T.ArrayType(T.StringType())),
    T.StructField("post_text", T.ArrayType(T.StringType())),
    T.StructField("table", T.ArrayType(T.ArrayType(T.StringType()))),
    T.StructField("qa", QA_SCHEMA),
])


def read_bronze(spark: SparkSession, path: str, source_commit: str, run_id: str) -> DataFrame:
    """Read raw FinQA JSON files (each a JSON array) and stamp lineage columns."""
    return (
        spark.read.schema(RAW_SCHEMA).option("multiLine", True).json(path)
        .withColumn("_source_file", F.col("_metadata.file_path"))
        .withColumn("split", F.regexp_extract("_source_file", r"([a-z_]+)\.json$", 1))
        .withColumn("_source_commit", F.lit(source_commit))
        .withColumn("_run_id", F.lit(run_id))
        .withColumn("_ingested_at", F.current_timestamp())
    )


def _strip(c):
    # Python's str.strip() removes all whitespace; Spark's trim() only spaces.
    return F.regexp_replace(c, r"^\s+|\s+$", "")


def documents(bronze: DataFrame) -> DataFrame:
    parts = F.split("filename", "/", 3)
    return (
        bronze.select(
            F.col("filename").alias("doc_id"),
            parts[0].alias("ticker"),
            parts[1].cast("int").alias("fiscal_year"),
            parts[2].alias("page"),
            "split",
            (F.size("pre_text") + F.size("post_text")).alias("n_text_units"),
            F.size("table").alias("n_table_rows"),
        )
        .dropDuplicates(["doc_id"])
    )


def evidence_units(bronze: DataFrame) -> DataFrame:
    pages = bronze.dropDuplicates(["filename"])

    text = (
        pages.select("filename", F.posexplode(F.concat("pre_text", "post_text")).alias("position", "text"))
        .select(
            F.concat("filename", F.lit("#text_"), "position").alias("unit_id"),
            F.col("filename").alias("doc_id"),
            F.lit("text").alias("kind"),
            "position", "text",
            F.lit(None).cast("string").alias("row_label"),
            F.array().cast("array<string>").alias("header"),
            F.array().cast("array<string>").alias("cells"),
        )
    )

    rows = pages.select(
        "filename",
        F.col("table")[0].alias("header"),
        F.posexplode("table").alias("position", "cells"),
    )
    # "row label | col header: value | ..." so a row is meaningful on its own.
    pairs = F.transform(
        F.slice("cells", 2, F.greatest(F.size("cells") - 1, F.lit(0))),
        lambda c, i: F.concat(
            F.coalesce(F.nullif(_strip(F.get("header", i + 1)), F.lit("")), F.concat(F.lit("col_"), i + 1)),
            F.lit(": "),
            _strip(c),
        ),
    )
    table = rows.select(
        F.concat("filename", F.lit("#table_"), "position").alias("unit_id"),
        F.col("filename").alias("doc_id"),
        F.lit("table_row").alias("kind"),
        "position",
        F.concat(F.coalesce(_strip(F.col("cells")[0]), F.lit("")), F.lit(" | "), F.array_join(pairs, " | ")).alias("text"),
        F.col("cells")[0].alias("row_label"),
        "header", "cells",
    )
    return text.unionByName(table)


_EXEC_RESULT = T.StructType([
    T.StructField("gold_exe_ans", T.StringType()),
    T.StructField("executor_value", T.StringType()),
    T.StructField("executor_matches_gold", T.BooleanType()),
    T.StructField("label_status", T.StringType()),
])


@F.udf(_EXEC_RESULT)
def _execute_and_classify(program, table, exe_ans, answer):
    # Imported inside the UDF so executors resolve the package from the
    # Fabric Environment rather than the driver's closure.
    from finsight.calc.program import ProgramError, execute, numbers_match
    from finsight.ingestion.finqa import classify_label

    # Spark renders JSON numbers via Java (1.0E-5); canonicalize to Python's
    # repr so silver values are identical no matter which engine wrote them.
    gold: float | str
    try:
        gold = float(exe_ans)
    except ValueError:
        gold = exe_ans
    try:
        res = execute(program, table=table)
        val, ok = str(res.value), numbers_match(res.value, gold, rel=1e-4, abs_=1e-4)
    except ProgramError:
        val, ok = None, False
    return (str(gold), val, ok, classify_label(answer, gold).value)


def questions(bronze: DataFrame) -> DataFrame:
    keys = F.array_sort(F.map_keys("qa.gold_inds"))
    has_table = F.exists(keys, lambda k: k.startswith("table"))
    has_text = F.exists(keys, lambda k: k.startswith("text"))
    return (
        bronze.select(
            F.col("id").alias("question_id"),
            F.col("filename").alias("doc_id"),
            "split",
            F.col("qa.question").alias("question"),
            F.col("qa.answer").alias("gold_answer_text"),
            F.col("qa.program").alias("gold_program"),
            F.transform(keys, lambda k: F.concat("filename", F.lit("#"), k)).alias("gold_unit_ids"),
            F.when(has_table & has_text, "table+text").when(has_table, "table").otherwise("text").alias("evidence_type"),
            F.size("qa.steps").alias("n_steps"),
            _execute_and_classify("qa.program", "table", "qa.exe_ans", "qa.answer").alias("r"),
            "_source_commit", "_run_id", "_ingested_at",
        )
        .select("*", "r.*").drop("r")
    )


def quality_checks(bronze: DataFrame, docs: DataFrame, qs: DataFrame) -> dict:
    """Return metrics and raise if a hard expectation fails (fails the pipeline run)."""
    n_bronze = bronze.count()
    n_q = qs.count()
    dup_q = n_q - qs.select("question_id").distinct().count()
    leak = bronze.groupBy("filename").agg(F.countDistinct("split").alias("n")).filter("n > 1").count()
    agree = qs.agg(F.avg(F.col("executor_matches_gold").cast("double"))).first()[0]
    status = {r["label_status"]: r["count"] for r in qs.groupBy("label_status").count().collect()}

    failures = []
    if n_q != n_bronze:
        failures.append(f"row count mismatch bronze={n_bronze} silver={n_q}")
    if dup_q:
        failures.append(f"{dup_q} duplicate question_ids")
    if leak:
        failures.append(f"{leak} pages appear in more than one split")
    if agree < 0.999:
        failures.append(f"executor agreement {agree:.4f} below 0.999")
    metrics = {"questions": n_q, "documents": docs.count(), "executor_agreement": round(agree, 4),
               "label_status": status, "failures": failures}
    if failures:
        raise ValueError(f"FinQA silver quality checks failed: {failures}")
    return metrics
