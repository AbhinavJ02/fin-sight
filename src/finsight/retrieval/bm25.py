"""Okapi BM25 for in-page retrieval.

Implemented here (not via bm25s) because a page is ~30 units and we want control over
where IDF comes from. `idf_scope="page"` computes document frequencies over the page's
own units; `"corpus"` uses frequencies from a reference corpus (the train-split pages),
which is steadier when a page has only a handful of units. bm25s serves as the reference
implementation in tests/test_bm25.py (D11).

Scoring matches bm25s method="lucene":
    idf(t)   = ln(1 + (N - df + 0.5) / (df + 0.5))
    tf_c(t)  = tf / (tf + k1 * (1 - b + b * dl / avgdl))
    score(d) = sum over unique query terms (in sorted order) of idf(t) * tf_c(t)
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Sequence

from finsight.retrieval.base import rank_by_score
from finsight.retrieval.text import tokenize
from finsight.schemas.finqa import EvidenceUnit


def idf(df: int, n: int) -> float:
    return math.log(1 + (n - df + 0.5) / (df + 0.5))


class CorpusStats:
    """Document frequencies over a reference corpus, for idf_scope="corpus"."""

    def __init__(self, token_lists: Iterable[list[str]]):
        self.df: Counter[str] = Counter()
        self.n = 0
        for toks in token_lists:
            self.df.update(set(toks))
            self.n += 1


def bm25_scores(query: list[str], docs: Sequence[list[str]], k1: float, b: float,
                stats: CorpusStats | None = None) -> list[float]:
    if stats is None:
        stats = CorpusStats(docs)
    avgdl = sum(len(d) for d in docs) / len(docs) or 1.0
    # Sorted, not a set: float addition is order-dependent, and set order varies between
    # processes, so exact ties could flip on the last bit from run to run (D12).
    terms = sorted(set(query))
    idfs = {t: idf(stats.df.get(t, 0), stats.n) for t in terms}
    scores = []
    for d in docs:
        tf = Counter(d)
        norm = k1 * (1 - b + b * len(d) / avgdl)
        scores.append(sum(idfs[t] * tf[t] / (tf[t] + norm) for t in terms if tf[t]))
    return scores


class BM25Retriever:
    name = "bm25"

    def __init__(self, k1: float = 1.2, b: float = 0.75, stem: bool = False,
                 stopwords: bool = True, idf_scope: str = "page",
                 corpus: Iterable[EvidenceUnit] | None = None):
        if idf_scope not in ("page", "corpus"):
            raise ValueError(f"idf_scope must be 'page' or 'corpus', got {idf_scope!r}")
        if idf_scope == "corpus" and corpus is None:
            raise ValueError("idf_scope='corpus' needs a reference corpus")
        self.k1, self.b, self.stem, self.stopwords, self.idf_scope = k1, b, stem, stopwords, idf_scope
        self._stats = (CorpusStats(self._tok(u.text) for u in corpus)
                       if idf_scope == "corpus" else None)

    def _tok(self, text: str) -> list[str]:
        return tokenize(text, stem=self.stem, stopwords=self.stopwords)

    def params(self) -> dict[str, str | int | float | bool]:
        return {"k1": self.k1, "b": self.b, "stem": self.stem,
                "stopwords": self.stopwords, "idf_scope": self.idf_scope}

    def rank(self, question: str, candidates: Sequence[EvidenceUnit]) -> list[str]:
        docs = [self._tok(u.text) for u in candidates]
        scores = bm25_scores(self._tok(question), docs, self.k1, self.b, self._stats)
        return rank_by_score({u.unit_id: s for u, s in zip(candidates, scores, strict=True)})
