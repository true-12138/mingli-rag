# -*- coding: utf-8 -*-
"""语义缓存随语料/索引变化自动失效。

核心约定：缓存上下文里带语料指纹，索引一变，精确层 key 自然不同；
本进程的语义向量索引也要清空——宁可全部 miss，也不能拿旧语料答案
冒充新语料。测试全部用注入的 fake encoder，不加载 BGE-M3。
"""
import os
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import semcache


class MapEncoder:
    """按问题查表返回向量；未登记的问题回退到默认向量。"""

    def __init__(self, mapping, default=(0.0, 1.0, 0.0)):
        self.mapping = {k: np.asarray(v, dtype=np.float32) for k, v in mapping.items()}
        self.default = np.asarray(default, dtype=np.float32)

    def encode(self, text, normalize_embeddings=True):
        if text in self.mapping:
            return self.mapping[text]
        return self.default


def _result(answer="答案 [1]", **overrides):
    out = {
        "can_answer": True,
        "answer": answer,
        "citations": [{"chunk_id": 1}],
        "citations_chunk_ids": [1],
        "invalid_citations": [],
        "invalid_output": False,
    }
    out.update(overrides)
    return out


def _use_fingerprint(value):
    """注入固定指纹；每次调用都会清掉指纹 TTL 缓存，便于测试中切换。"""
    semcache.set_fingerprint_provider(lambda: value)


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    # 外部环境里可能设了固定指纹，测试里先去掉，需要时再由用例自己设置。
    monkeypatch.delenv("MINGLI_CACHE_FINGERPRINT", raising=False)
    semcache.reset_for_tests()
    yield
    semcache.reset_for_tests()


def test_same_fingerprint_hits_exact_layer():
    """指纹不变时，同一问题第二次走精确层。"""
    semcache.set_encoder(MapEncoder({}))
    _use_fingerprint("fp-a")
    cache = semcache.get_cache()

    assert cache.check("羊刃分几种？")[0] is None
    assert cache.remember("羊刃分几种？", "rag", 5, _result()) is True

    hit, _ = cache.check("羊刃分几种？")
    assert hit is not None
    assert hit["cached"] is True
    assert hit["cache_kind"] == "exact"


def test_fingerprint_change_invalidates_exact_hit_and_clears_vectors():
    """指纹变化后精确层不再命中，进程内向量索引被清空。"""
    semcache.set_encoder(MapEncoder({"羊刃分几种？": [1.0, 0.0, 0.0]}))
    _use_fingerprint("fp-a")
    cache = semcache.get_cache()

    cache.check("羊刃分几种？")
    assert cache.remember("羊刃分几种？", "rag", 5, _result()) is True
    assert cache.info()["entries"] == 1

    _use_fingerprint("fp-b")
    hit, _ = cache.check("羊刃分几种？")
    assert hit is None
    assert cache.info()["entries"] == 0


def test_fingerprint_change_blocks_semantic_hit():
    """旧指纹下记住的问题，指纹变化后相似度再高也不命中。"""
    semcache.set_encoder(MapEncoder({
        "羊刃分几种？": [1.0, 0.0, 0.0],
        "羊刃一共有几种？": [0.999, 0.0447, 0.0],  # 相似度约 0.999 > 0.95
    }))
    semcache.THRESHOLD = 0.95
    _use_fingerprint("fp-a")
    cache = semcache.get_cache()

    cache.check("羊刃分几种？")
    cache.remember("羊刃分几种？", "rag", 5, _result())

    # 先确认语义层原本是通的
    hit, _ = cache.check("羊刃一共有几种？")
    assert hit is not None and hit["cache_kind"] == "semantic"

    _use_fingerprint("fp-b")
    hit, _ = cache.check("羊刃一共有几种？")
    assert hit is None
    assert cache.info()["entries"] == 0


def test_env_fingerprint_overrides_file_stat(monkeypatch):
    """MINGLI_CACHE_FINGERPRINT 非空时直接用，完全不碰文件 stat。"""
    monkeypatch.setenv("MINGLI_CACHE_FINGERPRINT", "pinned-fp")

    def _boom(*args, **kwargs):
        raise AssertionError("固定指纹模式下不应该 stat 任何文件")

    monkeypatch.setattr(os, "stat", _boom)

    assert semcache.corpus_fingerprint() == "pinned-fp"

    semcache.set_encoder(MapEncoder({}))
    cache = semcache.get_cache()
    assert cache.remember("q", "rag", 5, _result()) is True
    hit, _ = cache.check("q")
    assert hit is not None and hit["cache_kind"] == "exact"


def test_oserror_fingerprint_falls_back_to_unknown():
    """指纹算不出来时返回 unknown，缓存本身照常工作。"""
    def _broken():
        raise OSError("索引盘不可读")

    semcache.set_fingerprint_provider(_broken)
    assert semcache.corpus_fingerprint() == "unknown"

    semcache.set_encoder(MapEncoder({}))
    cache = semcache.get_cache()
    assert cache.remember("q", "rag", 5, _result()) is True
    hit, _ = cache.check("q")
    assert hit is not None and hit["cache_kind"] == "exact"
    assert cache.info()["fingerprint"] == "unknown"


def test_fingerprint_is_cached_within_ttl(monkeypatch):
    """TTL 内只算一次指纹；cache_key 也复用同一缓存。"""
    calls = {"n": 0}

    def _provider():
        calls["n"] += 1
        return "fp-{}".format(calls["n"])

    semcache.set_fingerprint_provider(_provider)
    monkeypatch.setattr(semcache, "FINGERPRINT_TTL", 30.0)

    assert semcache.corpus_fingerprint() == "fp-1"
    assert semcache.corpus_fingerprint() == "fp-1"
    semcache.cache_key("q", "rag", 5)
    assert calls["n"] == 1


def test_info_exposes_fingerprint_and_ttl():
    _use_fingerprint("abcdef0123456789extra")
    info = semcache.info()
    assert info["fingerprint"] == "abcdef0123456789"[:16]
    assert info["fingerprint_ttl_s"] == semcache.FINGERPRINT_TTL
