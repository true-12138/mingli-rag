# -*- coding: utf-8 -*-
"""倒排索引版 BM25，和 `rank_bm25.BM25Okapi` 打分一致，但不再被 GIL 锁死。

为什么要重写：rank_bm25 的 `get_scores` 是

    for q in query:
        q_freq = np.array([(doc.get(q) or 0) for doc in self.doc_freqs])

每个 query 词都遍历**全部 8,681 篇文档**做 Python 级 dict 查找。中文用字二元组
分词，一个 query 有 4–8 个词，就是 3–7 万次 dict 查找，全程持有 GIL：

    1 线程 31.9 QPS，8 线程 31.2 QPS —— 加线程完全不长吞吐
    /retrieve 64 并发只有 37 QPS，server_ms 从 35ms 膨胀到 350ms

改成倒排索引后，一次 query 只碰实际包含这些词的帖子（几千条），
用 numpy 一次性累加，Python 层的工作量从「词数 × 文档数」降到「词数」。

打分公式与 rank_bm25 完全一致（含 idf 的 epsilon 修正），
`tests/test_bm25_fast.py` 会在真实语料上逐条比对两边的分数。
"""
from __future__ import annotations

import math
from typing import Iterable, Sequence

import numpy as np


class FastBM25:
    """`rank_bm25.BM25Okapi` 的倒排索引实现，接口只保留 get_scores。"""

    def __init__(self, tokenized_corpus: Sequence[Sequence[str]],
                 k1: float = 1.5, b: float = 0.75, epsilon: float = 0.25):
        self.k1 = k1
        self.b = b
        self.epsilon = epsilon
        self.corpus_size = n = len(tokenized_corpus)
        if n == 0:
            self.vocab: dict[str, int] = {}
            self.indptr = np.zeros(1, dtype=np.int64)
            self.indices = np.zeros(0, dtype=np.int32)
            self.weights = np.zeros(0, dtype=np.float64)
            return

        # ---- 文档频率 → idf（公式与 rank_bm25 一致，含 epsilon 修正）----
        df: dict[str, int] = {}
        for toks in tokenized_corpus:
            for term in set(toks):
                df[term] = df.get(term, 0) + 1

        idf: dict[str, float] = {}
        idf_sum = 0.0
        negative: list[str] = []
        for term, freq in df.items():
            value = math.log(n - freq + 0.5) - math.log(freq + 0.5)
            idf[term] = value
            idf_sum += value
            if value < 0:
                negative.append(term)
        average_idf = idf_sum / len(idf) if idf else 0.0
        eps = epsilon * average_idf
        for term in negative:
            idf[term] = eps

        # ---- 每篇文档的长度归一化项 ----
        doc_len = np.fromiter((len(t) for t in tokenized_corpus), dtype=np.float64,
                              count=n)
        avgdl = float(doc_len.mean()) if n else 1.0
        norm = self.k1 * (1.0 - b + b * doc_len / (avgdl or 1.0))

        # ---- 倒排索引：term -> (doc_ids, weights) ----
        # 先计数再填，避免上百万个 Python list 的峰值内存
        self.vocab = {term: i for i, term in enumerate(df)}
        n_terms = len(self.vocab)
        counts = np.zeros(n_terms, dtype=np.int64)
        dfreq: list[dict[str, int]] = []
        for toks in tokenized_corpus:
            tf: dict[str, int] = {}
            for term in toks:
                tf[term] = tf.get(term, 0) + 1
            dfreq.append(tf)
            for term in tf:
                counts[self.vocab[term]] += 1

        indptr = np.zeros(n_terms + 1, dtype=np.int64)
        np.cumsum(counts, out=indptr[1:])
        indices = np.empty(int(indptr[-1]), dtype=np.int32)
        weights = np.empty(int(indptr[-1]), dtype=np.float64)
        cursor = indptr[:-1].copy()
        for doc_idx, tf in enumerate(dfreq):
            denom = norm[doc_idx]
            for term, freq in tf.items():
                col = self.vocab[term]
                pos = cursor[col]
                cursor[col] = pos + 1
                indices[pos] = doc_idx
                weights[pos] = idf[term] * freq * (self.k1 + 1.0) / (freq + denom)

        self.indptr = indptr
        self.indices = indices
        self.weights = weights

    def get_scores(self, query: Iterable[str]) -> np.ndarray:
        scores = np.zeros(self.corpus_size, dtype=np.float64)
        vocab = self.vocab
        indptr = self.indptr
        indices = self.indices
        weights = self.weights
        for term in query:
            col = vocab.get(term)
            if col is None:
                continue
            lo, hi = indptr[col], indptr[col + 1]
            if lo != hi:
                # 同一篇文档在一个词下只出现一次，直接花式索引累加即可
                scores[indices[lo:hi]] += weights[lo:hi]
        return scores
