"""Retriever interface for in-page retrieval (D2).

A retriever ranks *all* candidate units of one page for a question. Metrics need the
full ranking, and in-page candidate sets are small enough to score exhaustively.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Protocol

from finsight.schemas.finqa import EvidenceUnit


class Retriever(Protocol):
    name: str

    def params(self) -> dict[str, str | int | float | bool]: ...

    def rank(self, question: str, candidates: Sequence[EvidenceUnit]) -> list[str]:
        """Return every candidate unit_id, best first."""
        ...


def _tiebreak(unit_id: str) -> str:
    return hashlib.sha1(unit_id.encode()).hexdigest()


def rank_by_score(scores: dict[str, float]) -> list[str]:
    """Sort by score descending; break ties by a hash of unit_id.

    Ties are common (a question sharing no terms with most units scores them all 0).
    Breaking ties in page order would reward a retriever for wherever gold evidence
    tends to sit on the page; a hash is order-free and still reproducible.
    """
    return sorted(scores, key=lambda uid: (-scores[uid], _tiebreak(uid)))
