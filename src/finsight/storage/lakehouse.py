"""Delta table I/O. Same files run locally and in OneLake (abfss:// paths)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pyarrow as pa
from deltalake import DeltaTable, write_deltalake
from pydantic import BaseModel


def write_table(path: Path | str, rows: Sequence[BaseModel], mode: str = "overwrite") -> int:
    if not rows:
        raise ValueError(f"refusing to write empty table to {path}")
    records = [r.model_dump(mode="json") for r in rows]
    table = pa.Table.from_pylist(records)
    write_deltalake(str(path), table, mode=mode, schema_mode="overwrite" if mode == "overwrite" else None)
    return table.num_rows


def read_table(path: Path | str) -> pa.Table:
    return DeltaTable(str(path)).to_pyarrow_table()
