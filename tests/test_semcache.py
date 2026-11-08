# -*- coding: utf-8 -*-
"""语义缓存：精确层、语义层、额度隔离与 Redis 共享。"""
import sys
import time
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import semcache

try:
    import fakeredis
except ImportError:  # pragma: no cover - 依赖在 requirements 里
    fakeredis = None


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
        "llm_calls": 3,
        "usage": {"total_tokens": 99},
    }
    out.update(overrides)
    return out


@pytest.fixture(autouse=True)
def _reset():
    semcache.reset_for_tests()
    yield
    semcache.reset_for_tests()


def test_exact_hit_returns_answer_without_usage():
    semcache.set_encoder(MapEncoder({"羊刃分几种？": [1, 0, 0]}))
    cache = semcache.get_cache()

    assert cache.check("羊刃分几种？")[0] is None
    assert cache.remember("羊刃分几种？", "rag", 5, _result()) is True

    hit, _ = cache.check("羊刃分几种？")
    assert hit is not None
    assert hit["cached"] is True
    assert hit["cache_kind"] == "exact"
    assert hit["answer"] == "答案 [1]"
    # 只缓存答案/引用，不缓存 usage 与调用次数
    assert "usage" not in hit
    assert "llm_calls" not in hit


def test_question_normalization_matches_whitespace_and_punctuation():
    semcache.set_encoder(MapEncoder({}))
    cache = semcache.get_cache()
    cache.remember("  羊刃分几种？ ", "rag", 5, _result())

    hit, _ = cache.check("羊刃分几种", "rag", 5)
    assert hit is not None
    assert hit["cache_kind"] == "exact"


def test_semantic_hit_for_paraphrase():
    encoder = MapEncoder({
        "羊刃分几种？": [1.0, 0.0, 0.0],
        "羊刃一共有几种？": [0.995, 0.0999, 0.0],
    })
    semcache.set_encoder(encoder)
    semcache.THRESHOLD = 0.95
    cache = semcache.get_cache()

    cache.check("羊刃分几种？")  # miss，返回种子向量但不建索引
    cache.remember("羊刃分几种？", "rag", 5, _result())

    hit, _ = cache.check("羊刃一共有几种？")
    assert hit is not None
    assert hit["cache_kind"] == "semantic"
    assert hit["cache_similarity"] > 0.99


def test_semantic_below_threshold_is_miss():
    semcache.set_encoder(MapEncoder({
        "羊刃分几种？": [1.0, 0.0, 0.0],
        "完全无关的问题": [0.0, 1.0, 0.0],
    }))
    cache = semcache.get_cache()
    cache.check("羊刃分几种？")
    cache.remember("羊刃分几种？", "rag", 5, _result())

    hit, _ = cache.check("完全无关的问题")
    assert hit is None
    assert cache.stats()["miss"] == 2  # 两次 check 都 miss


def test_top_k_is_part_of_cache_identity():
    semcache.set_encoder(MapEncoder({
        "羊刃分几种？": [1.0, 0.0, 0.0],
    }))
    cache = semcache.get_cache()
    cache.check("羊刃分几种？")
    cache.remember("羊刃分几种？", "rag", 5, _result())

    hit, _ = cache.check("羊刃分几种？", "rag", 3)
    assert hit is None


def test_non_rag_modes_are_not_cached():
    semcache.set_encoder(MapEncoder({}))
    cache = semcache.get_cache()
    assert cache.remember("羊刃分几种？", "agent", 5, _result()) is False
    hit, vec = cache.check("羊刃分几种？", "multi", 5)
    assert hit is None and vec is None


@pytest.mark.parametrize("result", [
    _result(can_answer=None),
    _result(answer="   "),
    _result(invalid_output=True),
])
def test_invalid_results_are_not_cached(result):
    semcache.set_encoder(MapEncoder({}))
    assert semcache.get_cache().remember("q", "rag", 5, result) is False


def test_refusal_is_cacheable():
    semcache.set_encoder(MapEncoder({}))
    cache = semcache.get_cache()
    assert cache.remember("q", "rag", 5, _result(
        can_answer=False, answer="古籍中没有依据"
    )) is True
    hit, _ = cache.check("q")
    assert hit is not None and hit["can_answer"] is False


def test_redis_backend_shares_exact_hits_between_instances():
    if fakeredis is None:
        pytest.skip("fakeredis 未安装")
    semcache.set_encoder(MapEncoder({}))
    server = fakeredis.FakeRedis(decode_responses=True)

    writer = semcache.SemanticCache()
    writer.set_redis(server)
    assert writer.remember("羊刃分几种？", "rag", 5, _result()) is True

    reader = semcache.SemanticCache()
    reader.set_redis(server)
    hit, _ = reader.check("羊刃分几种？")
    assert hit is not None
    assert hit["cache_kind"] == "exact"
    assert reader.info()["backend"] == "redis"


def test_lru_bound_evicts_oldest(monkeypatch):
    semcache.set_encoder(MapEncoder({
        "q1": [1, 0, 0], "q2": [0, 1, 0], "q3": [0, 0, 1],
    }))
    monkeypatch.setattr(semcache, "MAX_ENTRIES", 2)
    cache = semcache.SemanticCache()
    cache._local.max_entries = 2

    for q in ("q1", "q2", "q3"):
        cache.check(q)
        cache.remember(q, "rag", 5, _result(q))

    hit, _ = cache.check("q1")
    assert hit is None  # 最旧的已被淘汰，三个向量两两正交也不会语义命中


def test_ttl_expiry(monkeypatch):
    semcache.set_encoder(MapEncoder({}))
    monkeypatch.setattr(semcache, "TTL", 0.05)
    cache = semcache.SemanticCache()
    cache.remember("q", "rag", 5, _result())
    assert cache.check("q")[0] is not None

    time.sleep(0.08)
    assert cache.check("q")[0] is None


def test_disabled_cache_is_a_noop(monkeypatch):
    semcache.set_encoder(MapEncoder({}))
    monkeypatch.setattr(semcache, "ENABLED", False)
    cache = semcache.get_cache()
    assert cache.remember("q", "rag", 5, _result()) is False
    assert cache.check("q") == (None, None)


def test_metrics_render_hit_and_miss_counts():
    semcache.set_encoder(MapEncoder({}))
    cache = semcache.get_cache()
    cache.check("q")
    cache.remember("q", "rag", 5, _result())
    cache.check("q")

    text = "\n".join(cache.render_metrics())
    assert 'mingli_semcache_hits_total{kind="exact"} 1' in text
    assert "mingli_semcache_misses_total 1" in text
    assert "mingli_semcache_stores_total 1" in text
    assert "mingli_semcache_entries 1" in text
