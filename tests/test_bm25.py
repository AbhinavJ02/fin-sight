import pytest

from finsight.retrieval.base import rank_by_score
from finsight.retrieval.bm25 import BM25Retriever, CorpusStats, bm25_scores
from finsight.retrieval.text import tokenize
from finsight.schemas.finqa import EvidenceKind, EvidenceUnit

DOCS = [
    "net revenue | 2015: $ 120 | 2014: $ 100",
    "operating income increased in 2015 due to higher revenue .",
    "the company repurchased 1,250 shares during 2014 .",
    "total debt | 2015: $ 2,400 | 2014: $ 2,150",
    "interest expense on debt was $ 85 million .",
]


def _units(texts):
    return [EvidenceUnit(unit_id=f"P#text_{i}", doc_id="P", kind=EvidenceKind.TEXT,
                         position=i, text=t) for i, t in enumerate(texts)]


def test_tokenize_keeps_numbers_and_joins_thousands():
    assert tokenize("Total debt was $ 2,400 in 2015.", stem=False, stopwords=False) == \
        ["total", "debt", "was", "2400", "in", "2015"]
    assert tokenize("what was the total debt", stem=False) == ["total", "debt"]
    assert tokenize("increased revenues", stopwords=False) == ["increas", "revenu"]


@pytest.mark.parametrize("query", ["what was total debt in 2015", "revenue growth 2014",
                                   "interest expense", "shares repurchased"])
def test_scores_match_bm25s_lucene(query):
    """bm25s is the reference implementation (D11). Same tokens in, same scores out."""
    bm25s = pytest.importorskip("bm25s")
    docs = [tokenize(d) for d in DOCS]
    q = list(dict.fromkeys(tokenize(query)))  # unique terms, as in our scorer
    ref = bm25s.BM25(method="lucene", k1=1.2, b=0.75)
    ref.index(docs, show_progress=False)
    q_known = [t for t in q if t in ref.vocab_dict]
    expected = ref.get_scores(q_known) if q_known else [0.0] * len(DOCS)
    ours = bm25_scores(q, docs, k1=1.2, b=0.75)
    assert ours == pytest.approx(list(expected), rel=1e-5)


def test_corpus_idf_differs_from_page_idf():
    docs = [tokenize(d) for d in DOCS]
    q = tokenize("total debt 2015")
    corpus = CorpusStats([["debt"]] * 50 + [["total"]] * 2 + [["2015"]] * 50)
    assert bm25_scores(q, docs, 1.2, 0.75, corpus) != bm25_scores(q, docs, 1.2, 0.75)


def test_rank_is_full_deterministic_and_ties_are_order_free():
    r = BM25Retriever()
    units = _units(DOCS)
    ranked = r.rank("what was total debt in 2015", units)
    assert sorted(ranked) == sorted(u.unit_id for u in units)
    assert ranked[0] == "P#text_3"
    assert ranked == r.rank("what was total debt in 2015", list(reversed(units)))
    # All-zero scores: order comes from the hash, not from input order.
    assert rank_by_score({"a": 0.0, "b": 0.0, "c": 0.0}) == rank_by_score({"c": 0.0, "a": 0.0, "b": 0.0})


def test_scores_do_not_depend_on_query_term_order():
    docs = [tokenize(d) for d in DOCS]
    q = tokenize("total debt interest expense revenue 2015 2014")
    assert bm25_scores(q, docs, 1.2, 0.75) == bm25_scores(list(reversed(q)), docs, 1.2, 0.75)


def test_last_bit_differences_are_ties():
    # 0.1 + 0.2 + 0.3 != 0.3 + 0.2 + 0.1 in floating point; ranking must not care.
    a, b = 0.1 + 0.2 + 0.3, 0.3 + 0.2 + 0.1
    assert a != b
    assert rank_by_score({"x": a, "y": b}) == rank_by_score({"x": b, "y": a})


def test_corpus_scope_requires_corpus():
    with pytest.raises(ValueError):
        BM25Retriever(idf_scope="corpus")
