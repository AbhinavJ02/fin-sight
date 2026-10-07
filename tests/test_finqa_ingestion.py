from finsight.ingestion.finqa import classify_label, transform_record
from finsight.schemas.finqa import EvidenceKind, LabelStatus

RECORD = {
    "id": "ABC/2015/page_10.pdf-1",
    "filename": "ABC/2015/page_10.pdf",
    "pre_text": ["revenue grew in 2015 ."],
    "post_text": ["amounts in millions ."],
    "table": [["", "2015", "2014"], ["net revenue", "$ 120", "$ 100"]],
    "qa": {
        "question": "what was the growth in net revenue?",
        "answer": "20%",
        "program": "subtract(120, 100), divide(#0, 100)",
        "exe_ans": 0.2,
        "steps": [{}, {}],
        "gold_inds": {"table_1": "...", "text_0": "..."},
    },
}


def test_transform_builds_ids_that_match_finqa_gold():
    doc, units, q = transform_record(RECORD, "test")
    assert doc.ticker == "ABC" and doc.fiscal_year == 2015
    ids = {u.unit_id for u in units}
    assert set(q.gold_unit_ids) <= ids
    assert q.evidence_type == "table+text"
    assert q.executor_matches_gold
    assert q.label_status == LabelStatus.CONSISTENT


def test_table_row_rendering_keeps_headers():
    _, units, _ = transform_record(RECORD, "test")
    row = next(u for u in units if u.kind == EvidenceKind.TABLE_ROW and u.position == 1)
    assert row.text == "net revenue | 2015: $ 120 | 2014: $ 100"


def test_label_classification():
    assert classify_label("14.1%", 0.14099) == LabelStatus.CONSISTENT
    assert classify_label("7%", 0.07157) == LabelStatus.ROUNDING
    assert classify_label("380", 3.8) == LabelStatus.CONFLICT
    assert classify_label("yes", "yes") == LabelStatus.BOOLEAN
    assert classify_label("n/a", 1.0) == LabelStatus.NON_NUMERIC
