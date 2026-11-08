# -*- coding: utf-8 -*-
"""检索里可单测的零件：BM25 分词器、重排。

单独成模块是因为 `retrieval.py` 一导入就要读 8,681 条语料和 34MB embedding，
不适合在 CI 里为了测一个分词函数而加载。这里的函数都是纯函数或懒加载对象，
不碰语料文件；`retrieval.py` 再把它们接进真正的检索链路。
"""
from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

import numpy as np


def bigram_tokens(text: str) -> list[str]:
    """字二元组：比单字更有区分度，不需要词典，作为默认分词器。"""
    s = "".join(ch for ch in text if not ch.isspace())
    if len(s) < 2:
        return list(s)
    return [s[i:i + 2] for i in range(len(s) - 1)]


def load_term_dict(terminology_dir: Path) -> list[str]:
    """从 data/terminology/*.jsonl 里取 term 字段，作为 jieba 用户词典。

    读不到就返回空列表——词典缺失不该让检索起不来。
    """
    words = set()
    try:
        paths = sorted(Path(terminology_dir).glob("*.jsonl"))
    except OSError:
        return []
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                term = (json.loads(line).get("term") or "").strip()
            except (json.JSONDecodeError, AttributeError):
                continue
            if 1 < len(term) <= 8:  # 单字交给 jieba 默认词表，太长的不是术语
                words.add(term)
    return sorted(words)


def make_tokenizer(mode: str, terminology_dir: Path | None = None):
    """返回 tokenize(text) -> list[str]。

    mode=jieba 但没装 jieba 时退回字二元组并打警告：宁可检索质量差一点，
    也不要让整个服务起不来。警告写 stderr——MCP stdio 通道把 stdout 当协议帧。
    """
    mode = (mode or "bigram").strip().lower()
    if mode == "bigram":
        return bigram_tokens
    # 写错模式名必须报错。以前这里对任何非 "jieba" 的值都静默返回二元组，
    # 于是 MINGLI_BM25_TOKENIZER=jieba_search 会悄悄跑成 bigram，
    # 结果文件看起来正常、结论却是假的。
    if mode not in ("jieba", "jieba_search"):
        raise ValueError(
            "MINGLI_BM25_TOKENIZER 只能是 bigram / jieba / jieba_search，收到 {!r}".format(mode))
    try:
        import jieba
    except ImportError:
        print("[warn] MINGLI_BM25_TOKENIZER={} 但没装 jieba，退回字二元组".format(mode),
              file=sys.stderr)
        return bigram_tokens

    terms = load_term_dict(terminology_dir) if terminology_dir else []
    # freq 给到 1e5：比默认词频强势，保证「正官格」不会被切成「正官/格」
    for term in terms:
        jieba.add_word(term, freq=100000)
    print("bm25 tokenizer: {} + {} 条术语".format(mode, len(terms)), file=sys.stderr)

    if mode == "jieba_search":
        # 索引模式：长词连同其子词一起输出（「正官格」→ 正官 / 官格 / 正官格），
        # 既保留词边界，又不会因为切法不同而漏掉子串匹配。
        def _tok(text: str) -> list[str]:
            return [t for t in jieba.cut_for_search(text) if t.strip()]
    else:
        def _tok(text: str) -> list[str]:
            return [t for t in jieba.lcut(text) if t.strip()]

    return _tok


class LazyReranker:
    """懒加载 CrossEncoder。接口只有 score(pairs)->np.ndarray，方便测试替换。

    bge-reranker-v2-m3 首次用要下几 GB 权重，放在构造时加载会让 API 启动变慢，
    所以和 BGE-M3 一样延到第一次真正重排。
    """

    def __init__(self, model_id: str):
        self.model_id = model_id
        self._m = None
        # 与 BGE-M3 同样的并发首载问题：不加锁会每个线程各载一份
        self._lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._m is not None

    def _load(self):
        with self._lock:
            if self._m is not None:
                return self._m
            os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
            from sentence_transformers import CrossEncoder

            self._m = CrossEncoder(self.model_id, max_length=512)
            return self._m

    def score(self, pairs: list[tuple[str, str]]):
        scores = self._load().predict(pairs)
        return np.asarray(scores, dtype="float32").reshape(-1)


def apply_rerank(query: str, items: list[dict], texts: list[str],
                 topk: int, scorer, on_error=None) -> list[dict]:
    """给候选 (query, 正文) 打分并重排。

    items 里每项要有 "idx"；texts 是 idx -> 正文的列表。打分失败时保留原顺序，
    只截断到 topk——重排是锦上添花，不能因为它把整条检索弄挂。
    """
    if not items:
        return items
    pairs = [(query, texts[it["idx"]]) for it in items]
    try:
        scores = np.asarray(scorer.score(pairs), dtype="float32").reshape(-1)
        if scores.shape[0] != len(items):
            raise ValueError("打分条数 {} 与候选数 {} 不一致".format(
                scores.shape[0], len(items)))
    except Exception as exc:  # 模型没下下来 / 显存不够 / 返回形状不对
        if on_error:
            on_error(exc)
        return items[:topk]
    order = np.argsort(-scores)[:topk]
    out = []
    for i in order:
        it = dict(items[int(i)])
        it["rerank_score"] = float(scores[int(i)])
        out.append(it)
    return out
