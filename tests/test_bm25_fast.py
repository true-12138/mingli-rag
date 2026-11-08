# -*- coding: utf-8 -*-
"""倒排索引版 BM25 必须和 rank_bm25 打分一致——否则检索评测的基线就变了。

在真实语料上逐条比对：任何一条分数差超过 1e-6 都算失败。排序容差比分数更严，
因为 R@5 只取决于排序，不取决于绝对分数。
"""
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("rank_bm25")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bm25_fast import FastBM25  # noqa: E402
from rank_bm25 import BM25Okapi  # noqa: E402

QUERIES = [
    "羊刃分几种",
    "正官七杀区别",
    "食神制杀",
    "天乙贵人",
    "大运流年",
]


@pytest.fixture(scope="module")
def corpora():
    import retrieval  # 复用真实语料的分词结果，避免重复处理
    return retrieval.tokenized_corpus, retrieval.tokenize


def test_scores_match_rank_bm25(corpora):
    tokenized, tokenize = corpora
    ref = BM25Okapi(tokenized)
    fast = FastBM25(tokenized)
    for query in QUERIES:
        tokens = tokenize(query)
        want = ref.get_scores(tokens)
        got = fast.get_scores(tokens)
        assert np.allclose(got, want, rtol=0, atol=1e-6), query


def test_ranking_matches_rank_bm25(corpora):
    tokenized, tokenize = corpora
    ref = BM25Okapi(tokenized)
    fast = FastBM25(tokenized)
    for query in QUERIES:
        tokens = tokenize(query)
        want = list(np.argsort(ref.get_scores(tokens))[::-1][:20])
        got = list(np.argsort(fast.get_scores(tokens))[::-1][:20])
        assert got == want, query


def test_unknown_terms_score_zero():
    fast = FastBM25([["羊刃", "七杀"], ["正官", "食神"]])
    scores = fast.get_scores(["完全不在库里的词"])
    assert np.all(scores == 0)


def test_empty_corpus_is_safe():
    fast = FastBM25([])
    assert fast.get_scores(["任意"]).shape == (0,)
