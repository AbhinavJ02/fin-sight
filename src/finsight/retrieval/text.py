"""Tokenization for lexical retrieval over FinQA text and rendered table rows."""

from __future__ import annotations

import re
from functools import lru_cache

# Words, or numbers with an optional decimal part. Signs and currency symbols are dropped:
# FinQA renders negatives as "$ -6781 ( 6781 )", so the magnitude survives either way.
_TOKEN = re.compile(r"[a-z]+|\d+(?:\.\d+)?")
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}\b)")

# Small, fixed English list. Kept in-repo so tokenization never shifts with a library update.
# Deliberately excludes words that carry meaning in financial questions
# ("total", "net", "change", "increase", "decrease", "percent").
_STOPWORDS_TEXT = """
a about after all also an and any are as at be been before being between both but by
can could did do does doing during each for from had has have having how if in into is
it its itself may might more most much must of on or other our over should so some such
than that the their them then there these they this those through to under up was we
were what when where which while who whom why will with would you your
"""
STOPWORDS = frozenset(_STOPWORDS_TEXT.split())


@lru_cache(maxsize=1)
def _stemmer():
    import Stemmer  # PyStemmer (retrieval extra)

    return Stemmer.Stemmer("english")


def tokenize(text: str, stem: bool = True, stopwords: bool = True) -> list[str]:
    toks = _TOKEN.findall(_THOUSANDS.sub("", text.lower()))
    if stopwords:
        toks = [t for t in toks if t not in STOPWORDS]
    if stem:
        toks = _stemmer().stemWords(toks)
    return toks
