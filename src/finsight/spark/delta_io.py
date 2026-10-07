"""Idempotent Delta writes for Fabric Lakehouse tables."""

from __future__ import annotations

from pyspark.sql import DataFrame, SparkSession


def merge_into(spark: SparkSession, df: DataFrame, table: str, keys: list[str]) -> str:
    """Upsert df into a managed Delta table. Re-running a load never duplicates rows.

    Returns "created" or "merged" so the caller can log what happened.
    """
    if not spark.catalog.tableExists(table):
        df.write.format("delta").saveAsTable(table)
        return "created"
    from delta.tables import DeltaTable  # available in the Fabric Spark runtime

    cond = " AND ".join(f"t.{k} = s.{k}" for k in keys)
    (
        DeltaTable.forName(spark, table).alias("t")
        .merge(df.alias("s"), cond)
        .whenMatchedUpdateAll()
        .whenNotMatchedInsertAll()
        .execute()
    )
    return "merged"
