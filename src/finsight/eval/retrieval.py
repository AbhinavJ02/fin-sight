"""In-page retrieval evaluation (D2 setting 1): rank the units of the gold page.

Core functions take plain silver models so the same code runs locally (deltalake) and in
a Fabric notebook (Spark rows -> models). `main` is the local CLI.

    python -m finsight.eval.retrieval --split dev --grid          # tune on dev
    python -m finsight.eval.retrieval --split test --write ...    # final configs only
"""

from __future__ import annotations

import argparse
import itertools
import json
import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path

import yaml

from finsight.eval.metrics import compute_all, expected_random, gold_ranks
from finsight.eval.stats import bootstrap_ci, paired_bootstrap
from finsight.provenance import git_commit, git_dirty
from finsight.retrieval.base import Retriever
from finsight.retrieval.bm25 import BM25Retriever
from finsight.schemas.eval import RetrievalQuestionResult, RetrievalRun
from finsight.schemas.finqa import EvidenceUnit, Question

HEADLINE = ("recall@3", "recall@5", "recall@10", "all_gold@3", "all_gold@5",
            "all_gold@10", "rr", "ndcg@5", "ndcg@10")
SILVER_TABLES = ("finqa_documents", "finqa_evidence_units", "finqa_questions")
# Stage 5 builds a program from the retrieved units, so it needs *all* of them (D12).
SELECTION_METRIC = "all_gold@5"
COMPARE_METRICS = (SELECTION_METRIC, "ndcg@10", "recall@3")


def group_units(units: Iterable[EvidenceUnit]) -> dict[str, list[EvidenceUnit]]:
    by_doc: dict[str, list[EvidenceUnit]] = defaultdict(list)
    for u in units:
        by_doc[u.doc_id].append(u)
    return by_doc


def evaluate(retriever: Retriever, questions: Sequence[Question],
             units_by_doc: dict[str, list[EvidenceUnit]], run_id: str) -> list[RetrievalQuestionResult]:
    results = []
    for q in questions:
        cands = units_by_doc[q.doc_id]
        ranked = retriever.rank(q.question, cands)
        if sorted(ranked) != sorted(u.unit_id for u in cands):
            raise ValueError(f"{retriever.name} did not return a full ranking for {q.question_id}")
        ranks = gold_ranks(ranked, q.gold_unit_ids)
        results.append(RetrievalQuestionResult(
            run_id=run_id, question_id=q.question_id, doc_id=q.doc_id, split=q.split,
            evidence_type=q.evidence_type, label_status=q.label_status.value,
            n_candidates=len(cands), n_gold=len(ranks), gold_ranks=ranks,
            top_unit_ids=ranked[:10], metrics=compute_all(ranks),
            random_metrics=expected_random(len(cands), len(ranks)),
        ))
    return results


def _mean(rows: Sequence[RetrievalQuestionResult], field: str, metric: str) -> float:
    return sum(getattr(r, field)[metric] for r in rows) / len(rows)


def _gold_bucket(n: int) -> str:
    return str(n) if n < 3 else "3+"


def summarize(results: Sequence[RetrievalQuestionResult]) -> tuple[dict, dict, dict]:
    """Overall means (system, random) and a breakdown with 95% CIs on the overall headline."""
    metrics = list(results[0].metrics)
    summary = {m: _mean(results, "metrics", m) for m in metrics}
    random_summary = {m: _mean(results, "random_metrics", m) for m in metrics}

    breakdown: dict = {"overall_ci95": {}}
    for m in HEADLINE:
        _, lo, hi = bootstrap_ci([r.metrics[m] for r in results])
        breakdown["overall_ci95"][m] = [lo, hi]
    for name, key in (("evidence_type", lambda r: r.evidence_type),
                      ("n_gold", lambda r: _gold_bucket(r.n_gold)),
                      ("label_status", lambda r: r.label_status)):
        groups: dict[str, list] = defaultdict(list)
        for r in results:
            groups[key(r)].append(r)
        breakdown[name] = {
            g: {"n": len(rows),
                "system": {m: _mean(rows, "metrics", m) for m in HEADLINE},
                "random": {m: _mean(rows, "random_metrics", m) for m in HEADLINE}}
            for g, rows in sorted(groups.items())
        }
    return summary, random_summary, breakdown


def build_run(run_id: str, split: str, retriever: Retriever,
              results: Sequence[RetrievalQuestionResult], silver_versions: dict[str, int],
              repo: Path) -> RetrievalRun:
    summary, random_summary, breakdown = summarize(results)
    return RetrievalRun(
        run_id=run_id, created_at=datetime.now(UTC).isoformat(), split=split,
        retriever=retriever.name, params_json=json.dumps(retriever.params(), sort_keys=True),
        n_questions=len(results), git_commit=git_commit(repo), git_dirty=git_dirty(repo),
        silver_versions_json=json.dumps(silver_versions, sort_keys=True),
        summary=summary, random_summary=random_summary, breakdown_json=json.dumps(breakdown),
    )


def compare_to_best(runs: dict[str, Sequence[RetrievalQuestionResult]],
                    metrics: Sequence[str] = COMPARE_METRICS) -> tuple[str, dict[str, dict]]:
    """Paired bootstrap of every config against the best one on SELECTION_METRIC.

    Returns (best label, {label: {metric: (diff, low, high)}}). A config whose interval
    includes 0 is indistinguishable from the best on this split.
    """
    def mean(rs):
        return sum(r.metrics[SELECTION_METRIC] for r in rs) / len(rs)

    best = max(runs, key=lambda k: mean(runs[k]))
    ref = {r.question_id: r for r in runs[best]}
    out = {}
    for label, rs in runs.items():
        if label == best:
            continue
        ordered = [ref[r.question_id] for r in rs]
        out[label] = {m: paired_bootstrap([r.metrics[m] for r in rs], [r.metrics[m] for r in ordered])
                      for m in metrics}
    return best, out


def format_run(run: RetrievalRun) -> str:
    ci = json.loads(run.breakdown_json)["overall_ci95"]
    lines = [f"{run.split} | {run.retriever} {run.params_json} | n={run.n_questions}",
             f"{'metric':<12}{'system':>8}{'95% CI':>18}{'random':>8}"]
    for m in HEADLINE:
        lo, hi = ci[m]
        lines.append(f"{m:<12}{run.summary[m]:>8.3f}   [{lo:.3f}, {hi:.3f}]{run.random_summary[m]:>8.3f}")
    return "\n".join(lines)


# ---------- local CLI ----------

def _load_silver(root: Path) -> tuple[list[Question], list[EvidenceUnit], dict[str, int], dict[str, str]]:
    from deltalake import DeltaTable  # local-only dependency

    silver = root / "silver"
    versions = {t: DeltaTable(str(silver / t)).version() for t in SILVER_TABLES}
    questions = [Question(**r) for r in DeltaTable(str(silver / "finqa_questions")).to_pyarrow_table().to_pylist()]
    units = [EvidenceUnit(**r) for r in DeltaTable(str(silver / "finqa_evidence_units")).to_pyarrow_table().to_pylist()]
    docs = DeltaTable(str(silver / "finqa_documents")).to_pyarrow_table().select(["doc_id", "split"]).to_pylist()
    return questions, units, versions, {d["doc_id"]: d["split"] for d in docs}


def _bm25_grid(train_units: list[EvidenceUnit]) -> list[BM25Retriever]:
    out = []
    for stem, stop, scope in itertools.product((False, True), (False, True), ("page", "corpus")):
        out.append(BM25Retriever(stem=stem, stopwords=stop, idf_scope=scope,
                                 corpus=train_units if scope == "corpus" else None))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/finqa.yaml")
    ap.add_argument("--split", choices=["dev", "test"], required=True)
    ap.add_argument("--grid", action="store_true", help="sweep BM25 tokenizer and IDF options (dev only)")
    ap.add_argument("--stem", action="store_true")
    ap.add_argument("--no-stopwords", action="store_true")
    ap.add_argument("--idf-scope", choices=["page", "corpus"], default="page")
    ap.add_argument("--k1", type=float, default=1.2)
    ap.add_argument("--b", type=float, default=0.75)
    ap.add_argument("--write", action="store_true", help="append run + per-question rows to gold tables")
    ap.add_argument("--allow-dirty", action="store_true", help="permit --write from an uncommitted tree")
    args = ap.parse_args()

    if args.grid and args.split == "test":
        ap.error("--grid tunes on dev; run only the chosen configurations on test")
    repo = Path(".")
    if args.write and git_dirty(repo) and not args.allow_dirty:
        ap.error("refusing --write from a dirty tree: results must be reproducible from a commit")

    cfg = yaml.safe_load(Path(args.config).read_text())
    root = Path(cfg["lakehouse_root"])
    questions, units, versions, doc_split = _load_silver(root)
    units_by_doc = group_units(units)
    qs = [q for q in questions if q.split == args.split]
    train_units = [u for u in units if doc_split[u.doc_id] == "train"]

    if args.grid:
        retrievers = _bm25_grid(train_units)
    else:
        retrievers = [BM25Retriever(k1=args.k1, b=args.b, stem=args.stem,
                                    stopwords=not args.no_stopwords, idf_scope=args.idf_scope,
                                    corpus=train_units if args.idf_scope == "corpus" else None)]

    by_config: dict[str, list[RetrievalQuestionResult]] = {}
    for retriever in retrievers:
        run_id = f"{datetime.now(UTC):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}"
        results = evaluate(retriever, qs, units_by_doc, run_id)
        run = build_run(run_id, args.split, retriever, results, versions, repo)
        by_config[run.params_json] = results
        print(format_run(run), end="\n\n")
        if args.write:
            from finsight.storage.lakehouse import write_table

            write_table(root / "gold" / "finqa_retrieval_runs", [run], mode="append")
            write_table(root / "gold" / "finqa_retrieval_results", results, mode="append")
            print(f"wrote run {run.run_id}")

    if len(by_config) > 1:
        best, diffs = compare_to_best(by_config)
        print(f"paired bootstrap vs best on {SELECTION_METRIC}: {best}")
        for label, ms in diffs.items():
            cells = "  ".join(f"{m} {d:+.3f} [{lo:+.3f}, {hi:+.3f}]" for m, (d, lo, hi) in ms.items())
            print(f"  {label}\n    {cells}")


if __name__ == "__main__":
    main()
