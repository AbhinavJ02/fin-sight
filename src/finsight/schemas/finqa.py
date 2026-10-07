"""Silver-layer models for the FinQA benchmark."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class EvidenceKind(StrEnum):
    TEXT = "text"
    TABLE_ROW = "table_row"


class LabelStatus(StrEnum):
    """How far we trust a benchmark label. Measured, not assumed."""

    CONSISTENT = "consistent"      # gold answer agrees with executed gold program
    ROUNDING = "rounding"          # agrees only within loose rounding (<=5%)
    CONFLICT = "conflict"          # answer and program disagree: noisy label
    NON_NUMERIC = "non_numeric"    # answer text could not be parsed
    BOOLEAN = "boolean"            # yes/no question


class Document(BaseModel):
    doc_id: str                    # e.g. "ADI/2009/page_49.pdf"
    ticker: str
    fiscal_year: int
    page: str
    split: str
    n_text_units: int
    n_table_rows: int


class EvidenceUnit(BaseModel):
    unit_id: str                   # "{doc_id}#text_3" / "{doc_id}#table_2"
    doc_id: str
    kind: EvidenceKind
    position: int                  # index within its kind, matches FinQA gold ids
    text: str                      # retrieval-ready rendering
    row_label: str | None = None
    header: list[str] = Field(default_factory=list)
    cells: list[str] = Field(default_factory=list)


class Question(BaseModel):
    question_id: str
    doc_id: str
    split: str
    question: str
    gold_answer_text: str
    gold_program: str
    gold_exe_ans: str              # str to hold both numbers and yes/no
    gold_unit_ids: list[str]
    evidence_type: str             # text | table | table+text
    n_steps: int
    executor_value: str | None     # our executor's result on gold program
    executor_matches_gold: bool    # our executor agrees with FinQA exe_ans
    label_status: LabelStatus
