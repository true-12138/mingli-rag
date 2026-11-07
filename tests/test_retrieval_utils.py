# -*- coding: utf-8 -*-
"""分词器与重排的离线测试（不加载语料、不下模型）。"""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import retrieval_utils as ru  # noqa: E402


def test_bigram_tokens_drops_whitespace():
    assert ru.bigram_tokens("正 官格") == ["正官", "官格"]
    assert ru.bigram_tokens("甲") == ["甲"]
    assert ru.bigram_tokens("") == []


def test_load_term_dict_reads_term_field(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text(
        "\n".join([
            json.dumps({"term": "正官格", "text": "x"}, ensure_ascii=False),
            json.dumps({"term": "甲", "text": "单字不要"}, ensure_ascii=False),
            json.dumps({"term": "九重天"}, ensure_ascii=False),
            "{不是 json",
        ]),
        encoding="utf-8",
    )
    assert ru.load_term_dict(tmp_path) == ["九重天", "正官格"]


def test_load_term_dict_missing_dir_is_empty(tmp_path):
    assert ru.load_term_dict(tmp_path / "nope") == []


def test_make_tokenizer_defaults_to_bigram():
    assert ru.make_tokenizer("bigram") is ru.bigram_tokens
    assert ru.make_tokenizer("") is ru.bigram_tokens


def test_make_tokenizer_jieba_falls_back_without_package(monkeypatch):
    # 没装 jieba 时不能抛异常，否则整个检索起不来
    monkeypatch.setitem(sys.modules, "jieba", None)
    assert ru.make_tokenizer("jieba") is ru.bigram_tokens


class _FakeScorer:
    def __init__(self, scores):
        self.scores = scores
        self.calls = []

    def score(self, pairs):
        self.calls.append(pairs)
        return np.asarray(self.scores, dtype="float32")


def test_apply_rerank_reorders_and_limits():
    items = [{"idx": 0, "scores": 0.9}, {"idx": 1, "scores": 0.8}, {"idx": 2, "scores": 0.7}]
    texts = ["甲文", "乙文", "丙文"]
    scorer = _FakeScorer([0.1, 0.9, 0.5])
    out = ru.apply_rerank("问题", items, texts, 2, scorer)
    assert [it["idx"] for it in out] == [1, 2]
    assert out[0]["rerank_score"] == pytest.approx(0.9)
    # 原 items 不被就地改写
    assert items[0]["idx"] == 0 and "rerank_score" not in items[0]


def test_apply_rerank_falls_back_on_error():
    items = [{"idx": 0}, {"idx": 1}, {"idx": 2}]

    class Boom:
        def score(self, pairs):
            raise RuntimeError("模型没下下来")

    errs = []
    out = ru.apply_rerank("q", items, ["a", "b", "c"], 2, Boom(), on_error=errs.append)
    assert [it["idx"] for it in out] == [0, 1]
    assert len(errs) == 1


def test_apply_rerank_rejects_wrong_score_count():
    class Short:
        def score(self, pairs):
            return [0.5]

    items = [{"idx": 0}, {"idx": 1}]
    out = ru.apply_rerank("q", items, ["a", "b"], 2, Short())
    assert [it["idx"] for it in out] == [0, 1]  # 形状不对时退回原顺序
