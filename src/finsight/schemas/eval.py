"""Gold-layer models for retrieval evaluation runs."""

from __future__ import annotations

from pydantic import BaseModel


class RetrievalQuestionResult(BaseModel):
    run_id: str
    question_id: str
    doc_id: str
    split: str
    evidence_type: str
    label_status: str
    n_candidates: int
    n_gold: int
    gold_ranks: list[int]          # 1-based; every metric derives from these
    top_unit_ids: list[str]        # first 10 of the ranking, for inspection
    metrics: dict[str, float]
    random_metrics: dict[str, float]


class RetrievalRun(BaseModel):
    run_id: str
    created_at: str
    split: str
    retriever: str
    params_json: str
    n_questions: int
    git_commit: str | None
    git_dirty: bool
    silver_versions_json: str      # Delta version of each silver table read
    summary: dict[str, float]      # overall means
    random_summary: dict[str, float]
    breakdown_json: str            # means by evidence_type / n_gold / label_status, with CIs
