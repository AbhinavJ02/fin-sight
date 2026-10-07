"""FinQA ingestion: raw JSON (bronze) -> documents, evidence units, questions (silver).

Bronze is an untouched copy of the source files plus a manifest with hashes.
Silver is normalized and carries a measured label-quality status per question.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import yaml

from finsight.calc.program import ProgramError, execute, numbers_match, parse_number
from finsight.schemas.finqa import (
    Document,
    EvidenceKind,
    EvidenceUnit,
    LabelStatus,
    Question,
)

# ---------- bronze ----------

def ingest_bronze(src_dir: Path, splits: list[str], bronze_dir: Path) -> dict:
    bronze_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for split in splits:
        src = src_dir / "dataset" / f"{split}.json"
        dst = bronze_dir / f"{split}.json"
        shutil.copyfile(src, dst)
        files.append({"split": split, "path": dst.name, "sha256": _sha256(dst), "bytes": dst.stat().st_size})
    manifest = {
        "source": "FinQA",
        "commit": _git_commit(src_dir),
        "ingested_at": datetime.now(UTC).isoformat(),
        "files": files,
    }
    (bronze_dir / "_manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _git_commit(repo: Path) -> str | None:
    try:
        return subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


# ---------- silver ----------

def _render_row(header: list[str], row: list[str]) -> str:
    """Render a table row with its column headers so it survives chunking alone."""
    label = row[0].strip() if row else ""
    pairs = []
    for i, cell in enumerate(row[1:], start=1):
        col = header[i].strip() if i < len(header) and header[i].strip() else f"col_{i}"
        pairs.append(f"{col}: {cell.strip()}")
    return f"{label} | " + " | ".join(pairs)


def _split_doc_id(doc_id: str) -> tuple[str, int, str]:
    ticker, year, page = doc_id.split("/", 2)
    return ticker, int(year), page


def classify_label(answer_text: str, exe_ans: float | str) -> LabelStatus:
    if isinstance(exe_ans, str):
        return LabelStatus.BOOLEAN
    try:
        a = parse_number(answer_text)
    except ProgramError:
        return LabelStatus.NON_NUMERIC
    # FinQA answers like "12%" are written in percent units while exe_ans is a ratio.
    a_raw = parse_number(answer_text.rstrip("%")) if answer_text.strip().endswith("%") else a
    for cand in (a, a_raw):
        if numbers_match(exe_ans, cand, rel=0.01, abs_=5e-4):
            return LabelStatus.CONSISTENT
    for cand in (a, a_raw):
        if numbers_match(exe_ans, cand, rel=0.05, abs_=5e-3):
            return LabelStatus.ROUNDING
    return LabelStatus.CONFLICT


def transform_record(rec: dict, split: str) -> tuple[Document, list[EvidenceUnit], Question]:
    doc_id = rec["filename"]
    ticker, year, page = _split_doc_id(doc_id)
    text_sents = list(rec["pre_text"]) + list(rec["post_text"])
    table = rec["table"]
    header = table[0] if table else []

    units: list[EvidenceUnit] = []
    for i, s in enumerate(text_sents):
        units.append(EvidenceUnit(unit_id=f"{doc_id}#text_{i}", doc_id=doc_id,
                                  kind=EvidenceKind.TEXT, position=i, text=s))
    # FinQA's gold ids index table rows including the header row (table_0).
    for i, row in enumerate(table):
        units.append(EvidenceUnit(unit_id=f"{doc_id}#table_{i}", doc_id=doc_id,
                                  kind=EvidenceKind.TABLE_ROW, position=i,
                                  text=_render_row(header, row), row_label=row[0] if row else None,
                                  header=header, cells=row))

    doc = Document(doc_id=doc_id, ticker=ticker, fiscal_year=year, page=page, split=split,
                   n_text_units=len(text_sents), n_table_rows=len(table))

    qa = rec["qa"]
    gold = list(qa.get("gold_inds", {}).keys())
    has_t = any(g.startswith("table") for g in gold)
    has_x = any(g.startswith("text") for g in gold)
    ev_type = "table+text" if has_t and has_x else "table" if has_t else "text"

    exe_ans = qa["exe_ans"]
    try:
        res = execute(qa["program"], table=table)
        exec_val: str | None = str(res.value)
        exec_ok = numbers_match(res.value, exe_ans, rel=1e-4, abs_=1e-4)
    except ProgramError:
        exec_val, exec_ok = None, False

    q = Question(
        question_id=rec["id"], doc_id=doc_id, split=split, question=qa["question"],
        gold_answer_text=str(qa["answer"]), gold_program=qa["program"], gold_exe_ans=str(exe_ans),
        gold_unit_ids=[f"{doc_id}#{g}" for g in gold], evidence_type=ev_type,
        n_steps=len(qa.get("steps", [])), executor_value=exec_val,
        executor_matches_gold=exec_ok, label_status=classify_label(str(qa["answer"]), exe_ans),
    )
    return doc, units, q


def build_silver(bronze_dir: Path, splits: list[str]) -> tuple[list[Document], list[EvidenceUnit], list[Question]]:
    docs: dict[str, Document] = {}
    units: dict[str, EvidenceUnit] = {}
    questions: list[Question] = []
    seen_q: set[str] = set()
    for split in splits:
        for rec in json.loads((bronze_dir / f"{split}.json").read_text()):
            doc, us, q = transform_record(rec, split)
            if q.question_id in seen_q:
                raise ValueError(f"duplicate question id {q.question_id}")
            seen_q.add(q.question_id)
            prev = docs.get(doc.doc_id)
            if prev and prev.split != doc.split:
                raise ValueError(f"page {doc.doc_id} appears in {prev.split} and {doc.split}")
            docs[doc.doc_id] = doc
            for u in us:
                units.setdefault(u.unit_id, u)
            questions.append(q)
    return list(docs.values()), list(units.values()), questions


def quality_report(docs: list[Document], questions: list[Question]) -> dict:
    by_split: dict[str, dict] = {}
    for split in sorted({q.split for q in questions}):
        qs = [q for q in questions if q.split == split]
        by_split[split] = {
            "questions": len(qs),
            "documents": sum(1 for d in docs if d.split == split),
            "tickers": len({d.ticker for d in docs if d.split == split}),
            "executor_agreement": round(sum(q.executor_matches_gold for q in qs) / len(qs), 4),
            "label_status": dict(Counter(q.label_status.value for q in qs)),
            "evidence_type": dict(Counter(q.evidence_type for q in qs)),
        }
    return {"generated_at": datetime.now(UTC).isoformat(), "splits": by_split}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/finqa.yaml")
    ap.add_argument("--src", required=True, help="path to a FinQA checkout")
    args = ap.parse_args()
    from finsight.storage.lakehouse import (
        write_table,  # local-only dependency (deltalake)
    )

    cfg = yaml.safe_load(Path(args.config).read_text())
    root = Path(cfg["lakehouse_root"])
    splits = cfg["splits"]

    manifest = ingest_bronze(Path(args.src), splits, root / "bronze" / "finqa")
    docs, units, questions = build_silver(root / "bronze" / "finqa", splits)
    write_table(root / "silver" / "finqa_documents", docs)
    write_table(root / "silver" / "finqa_evidence_units", units)
    write_table(root / "silver" / "finqa_questions", questions)

    report = quality_report(docs, questions) | {"bronze_commit": manifest["commit"]}
    out = root / "reports" / "finqa_quality.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
