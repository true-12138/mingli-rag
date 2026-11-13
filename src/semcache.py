# -*- coding: utf-8 -*-
"""语义缓存：同一个问题不重复打 LLM。

分两层，命中顺序从便宜到贵：

1. **精确层**：问题规范化（NFKC、小写、压空白、去尾标点）后哈希。
   条目写 Redis，多 worker / 多实例共享；Redis 不可用或没配置时退化为
   进程内 LRU，接口不变。
2. **语义层**：问题向量余弦相似度 >= `MINGLI_CACHE_THRESHOLD` 的最近条目。
   Redis 的普通镜像没有 RediSearch/vector 模块，所以向量索引只保存在
   各进程内（有界 LRU），答案正文仍以 Redis 为准。多 worker 下语义命中
   是各进程各自学习的；精确命中跨 worker 共享。

只缓存 **RAG 单轮** 回答：agent / multi 带工具轨迹和步数，多轮对话同一句
问题在不同上下文里答案不同，按问题复用会串答案。用户自带 key 的请求也不
缓存，避免拿别人的结果冒充自己 key 的输出。

缓存条目只保留答案与引用，不保留 usage / trace。命中时由调用方把
`usage` 置零、标记 `cached=true`，指标里能区分「缓存命中的快」与
「模型变快」。

**随语料/索引自动失效**：缓存 key 的上下文里带一个语料指纹
（`all_records.pkl` / `embeddings.npy` / `chunks/` 的轻量 stat 摘要）。
索引一变，精确层 key 自然不同，Redis 里的旧条目只会自然过期，不需要
扫描删除；本进程的语义向量索引也会被清空。代价是指纹最多滞后
`MINGLI_CACHE_FINGERPRINT_TTL` 秒（默认 30）才刷新——这段时间里宁可
继续用旧索引，也不能让每次请求都去 stat 一遍磁盘。

精度优先于命中率：指纹算不出来时统一退化成 `"unknown"`，缓存照常
工作；所有实例都算不出来时大家仍然共享同一个 `"unknown"` 命名空间，
只是失去了「语料一变就失效」的保护。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
import unicodedata
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable

import numpy as np

logger = logging.getLogger("mingli.semcache")

REDIS_URL = os.environ.get("MINGLI_REDIS_URL", "").strip()
KEY_PREFIX = os.environ.get("MINGLI_REDIS_PREFIX", "mingli")

ENABLED = os.environ.get("MINGLI_CACHE_ENABLED", "1") != "0"
SEMANTIC = os.environ.get("MINGLI_CACHE_SEMANTIC", "1") != "0"
THRESHOLD = float(os.environ.get("MINGLI_CACHE_THRESHOLD", "0.95"))
TTL = float(os.environ.get("MINGLI_CACHE_TTL", "86400"))
MAX_ENTRIES = int(os.environ.get("MINGLI_CACHE_MAX_ENTRIES", "1000"))
# 指纹最多滞后这么久才刷新：既能让语料更新尽快生效，又避免每个请求都
# stat 一遍索引文件。
FINGERPRINT_TTL = float(os.environ.get("MINGLI_CACHE_FINGERPRINT_TTL", "30"))

# 只缓存能独立复用的字段；trace_id / elapsed_ms / usage 每次重新生成。
_CACHE_FIELDS = (
    "can_answer",
    "answer",
    "citations",
    "citations_chunk_ids",
    "invalid_citations",
    "invalid_output",
)


# ---------- 向量编码（可注入，单测不加载 BGE-M3） ----------

_ENCODER: Any = None
_encoder_lock = threading.Lock()


def set_encoder(encoder: Any) -> None:
    """单测 / 自定义部署用：传一个带 `.encode(text, normalize_embeddings=True)` 的对象。"""
    global _ENCODER
    with _encoder_lock:
        _ENCODER = encoder


def _encode(text: str) -> np.ndarray:
    encoder = _ENCODER
    if encoder is None:
        import retrieval  # 延迟导入：模块导入时不触发 35MB 语料与模型加载

        encoder = retrieval.model
        set_encoder(encoder)
    vec = np.asarray(
        encoder.encode(text, normalize_embeddings=True), dtype=np.float32
    ).reshape(-1)
    norm = float(np.linalg.norm(vec))
    if norm > 0:
        vec = vec / norm
    return vec


# ---------- 语料指纹（索引变化 → 缓存自动失效） ----------

_REPO_ROOT = Path(__file__).resolve().parent.parent

_fingerprint_lock = threading.Lock()
_fingerprint_cache: "tuple[float, str] | None" = None
_fingerprint_provider: "Callable[[], str] | None" = None


def set_fingerprint_provider(provider: "Callable[[], str] | None") -> None:
    """测试 / 自定义部署注入指纹来源；传 None 恢复默认的文件 stat。"""
    global _fingerprint_provider, _fingerprint_cache
    with _fingerprint_lock:
        _fingerprint_provider = provider
        # 换 provider 必须立刻生效，不能沿用旧指纹的 TTL 缓存。
        _fingerprint_cache = None


def _data_dir() -> Path:
    """与 corpus.data_dir() 保持一致，但不导入它以免触发语料加载。"""
    return Path(os.environ.get("MINGLI_DATA_DIR", _REPO_ROOT / "data"))


def _default_fingerprint() -> str:
    """对索引产物做轻量摘要。

    大文件只取 (相对路径, size, mtime_ns)；`chunks/` 可能有上万个小文件，
    逐个 stat 太贵，只取目录 mtime 和条目数——重建语料时目录必然被重写，
    足以触发失效。
    """
    data = _data_dir()
    parts: "list[tuple[str, int, int]]" = []
    for name in ("all_records.pkl", "embeddings.npy"):
        st = (data / name).stat()
        parts.append((name, int(st.st_size), int(st.st_mtime_ns)))
    chunks = data / "chunks"
    cst = chunks.stat()
    with os.scandir(chunks) as it:
        count = sum(1 for _ in it)
    parts.append(("chunks", count, int(cst.st_mtime_ns)))

    payload = json.dumps(parts, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def corpus_fingerprint() -> str:
    """返回当前语料/索引指纹。

    优先级：环境变量（固定部署 / 测试） > 注入的 provider > 默认文件 stat。
    结果在 `FINGERPRINT_TTL` 内复用；任何 OSError 都退化为 `"unknown"`，
    缓存不能因为指纹算不出来而报错。
    """
    global _fingerprint_cache
    pinned = os.environ.get("MINGLI_CACHE_FINGERPRINT", "").strip()
    if pinned:
        return pinned

    now = time.time()
    with _fingerprint_lock:
        cached = _fingerprint_cache
        if cached is not None and cached[0] > now:
            return cached[1]
        provider = _fingerprint_provider

    try:
        value = provider() if provider is not None else _default_fingerprint()
    except OSError as exc:
        logger.warning("语料指纹计算失败，退化为 unknown：%s", exc)
        value = "unknown"

    value = str(value or "unknown")
    with _fingerprint_lock:
        _fingerprint_cache = (time.time() + FINGERPRINT_TTL, value)
    return value


# ---------- 规范化与 key ----------


def normalize_question(question: str) -> str:
    text = unicodedata.normalize("NFKC", str(question or ""))
    text = " ".join(text.strip().lower().split())
    return text.rstrip("？?。.!！；;，,、 ")


def _context(mode: str, top_k: int, fingerprint: "str | None" = None) -> str:
    """缓存上下文带上语料指纹：索引一变，key 自然换一套。"""
    fp = corpus_fingerprint() if fingerprint is None else fingerprint
    return "{}|{}|{}".format(mode, int(top_k), fp)


def _key_for(question: str, mode: str, context: str) -> str:
    digest = hashlib.sha256(
        "{}|{}".format(context, normalize_question(question)).encode("utf-8")
    ).hexdigest()
    return "{}-{}".format(mode, digest[:32])


def cache_key(question: str, mode: str, top_k: int) -> str:
    # 签名保持不变；指纹在内部取，保证调用方无感。
    return _key_for(question, mode, _context(mode, top_k))


# ---------- 存储 ----------


class _LocalStore:
    """有界 LRU，兼容 Redis 不可用。"""

    def __init__(self, max_entries: int) -> None:
        self._lock = threading.Lock()
        self._items: "OrderedDict[str, tuple[float, str]]" = OrderedDict()
        self.max_entries = max_entries

    def get(self, key: str) -> str | None:
        now = time.time()
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            expires, raw = item
            if expires <= now:
                self._items.pop(key, None)
                return None
            self._items.move_to_end(key)
            return raw

    def set(self, key: str, raw: str, ttl: float) -> None:
        with self._lock:
            self._items[key] = (time.time() + ttl, raw)
            self._items.move_to_end(key)
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)

    def __len__(self) -> int:
        return len(self._items)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


class SemanticCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._local = _LocalStore(MAX_ENTRIES)
        # key -> (context, expires, vector)
        self._vectors: "OrderedDict[str, tuple[str, float, np.ndarray]]" = OrderedDict()
        # 当前向量索引是按哪个语料指纹建立的；None 表示本进程还没建过索引。
        self._index_fingerprint: "str | None" = None
        self._redis: Any = None
        self._redis_broken = False
        self._counts = {"exact": 0, "semantic": 0, "miss": 0, "store": 0, "error": 0}

    # --- Redis ---

    def _redis_client(self) -> Any:
        if self._redis is not None:
            return None if self._redis_broken else self._redis
        if not REDIS_URL or self._redis_broken:
            return None
        if self._redis is None:
            try:
                import redis

                self._redis = redis.Redis.from_url(
                    REDIS_URL, decode_responses=True, socket_timeout=2.0
                )
            except Exception as exc:  # noqa: BLE001
                self._redis_broken = True
                self._record_error(exc)
                return None
        return self._redis

    def set_redis(self, client: Any) -> None:
        """测试注入（fakeredis）。"""
        self._redis = client
        self._redis_broken = client is None

    def _redis_key(self, key: str) -> str:
        return "{}:semcache:{}".format(KEY_PREFIX, key)

    def _get(self, key: str) -> str | None:
        client = self._redis_client()
        if client is not None:
            try:
                raw = client.get(self._redis_key(key))
            except Exception as exc:  # noqa: BLE001
                self._redis_broken = True
                self._record_error(exc)
            else:
                if raw is not None:
                    # 顺手回填本地，Redis 抖动时还能撑一阵
                    self._local.set(key, raw, TTL)
                    return raw
        return self._local.get(key)

    def _set(self, key: str, raw: str) -> None:
        self._local.set(key, raw, TTL)
        client = self._redis_client()
        if client is not None:
            try:
                client.set(self._redis_key(key), raw, ex=int(TTL))
            except Exception as exc:  # noqa: BLE001
                self._redis_broken = True
                self._record_error(exc)

    # --- 索引 ---

    def _sync_fingerprint(self, fingerprint: str) -> None:
        """语料指纹变了就清空本进程语义索引。

        精度优先：旧向量哪怕余弦相似度再高，也是旧语料的答案。精确层靠
        key 里的指纹自然隔离；这里只处理本进程的向量索引，避免拿旧答案
        冒充新语料。
        """
        with self._lock:
            if self._index_fingerprint == fingerprint:
                return
            previous = self._index_fingerprint
            self._index_fingerprint = fingerprint
            stale = bool(self._vectors)
            if stale:
                self._vectors.clear()
        if previous is not None and stale:
            logger.info(
                "语料指纹由 %s 变为 %s，清空本进程语义索引",
                previous[:16],
                fingerprint[:16],
            )

    def _index(self, key: str, context: str, vector: np.ndarray) -> None:
        with self._lock:
            self._vectors[key] = (context, time.time() + TTL, vector)
            self._vectors.move_to_end(key)
            while len(self._vectors) > MAX_ENTRIES:
                self._vectors.popitem(last=False)

    def _has_entries(self, context: str) -> bool:
        now = time.time()
        with self._lock:
            return any(
                ctx == context and expires > now
                for ctx, expires, _ in self._vectors.values()
            )

    def _nearest(self, context: str, vector: np.ndarray) -> tuple[str | None, float]:
        now = time.time()
        best_key: str | None = None
        best = -1.0
        with self._lock:
            for key, (ctx, expires, vec) in list(self._vectors.items()):
                if expires <= now:
                    self._vectors.pop(key, None)
                    continue
                if ctx != context:
                    continue
                sim = float(np.dot(vector, vec))
                if sim > best:
                    best, best_key = sim, key
        return best_key, best

    def _forget(self, key: str) -> None:
        with self._lock:
            self._vectors.pop(key, None)

    # --- 统计 ---

    def _record(self, kind: str) -> None:
        with self._lock:
            self._counts[kind] += 1

    def _record_error(self, exc: Exception) -> None:
        with self._lock:
            self._counts["error"] += 1
        logger.warning("语义缓存降级：%s", exc)

    def stats(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counts)

    # --- 主接口 ---

    def check(
        self, question: str, mode: str = "rag", top_k: int = 5
    ) -> tuple[dict[str, Any] | None, np.ndarray | None]:
        """返回 (命中条目, 本次问题的向量)。

        向量在 miss 时也返回，`remember` 直接复用，避免一次回答编码两遍。
        语义层关闭或编码失败时向量为 None。
        """
        if not ENABLED or mode != "rag" or not normalize_question(question):
            return None, None

        fingerprint = corpus_fingerprint()
        self._sync_fingerprint(fingerprint)
        context = _context(mode, top_k, fingerprint)
        key = _key_for(question, mode, context)

        raw = self._get(key)
        if raw is not None:
            payload = self._decode(raw)
            if payload is not None:
                self._record("exact")
                return self._decorate(payload, "exact", 1.0), None

        vector: np.ndarray | None = None
        # 索引为空时不做语义比对，省掉第一次请求的模型加载；remember 会
        # 用一次编码把索引种上。
        if SEMANTIC and self._has_entries(context):
            try:
                vector = _encode(question)
            except Exception as exc:  # noqa: BLE001 - 缓存故障不能影响回答
                self._record_error(exc)

        if vector is not None:
            best_key, similarity = self._nearest(context, vector)
            if best_key is not None and similarity >= THRESHOLD:
                raw = self._get(best_key)
                payload = self._decode(raw) if raw is not None else None
                if payload is not None:
                    self._record("semantic")
                    return self._decorate(payload, "semantic", similarity), vector
                self._forget(best_key)

        self._record("miss")
        return None, vector

    def remember(
        self,
        question: str,
        mode: str,
        top_k: int,
        result: dict[str, Any],
        query_vec: np.ndarray | None = None,
    ) -> bool:
        if not ENABLED or mode != "rag" or not normalize_question(question):
            return False
        payload = {key: result.get(key) for key in _CACHE_FIELDS if key in result}
        if payload.get("can_answer") is None or payload.get("invalid_output"):
            return False
        if not str(payload.get("answer") or "").strip():
            return False

        fingerprint = corpus_fingerprint()
        self._sync_fingerprint(fingerprint)
        context = _context(mode, top_k, fingerprint)
        key = _key_for(question, mode, context)
        entry = {
            "question": str(question)[:200],
            "payload": payload,
            "created": round(time.time(), 3),
        }
        self._set(key, json.dumps(entry, ensure_ascii=False))

        if SEMANTIC:
            vector = query_vec
            if vector is None:
                try:
                    vector = _encode(question)
                except Exception as exc:  # noqa: BLE001
                    self._record_error(exc)
            if vector is not None:
                self._index(key, context, vector)

        self._record("store")
        return True

    # --- 内部 ---

    @staticmethod
    def _decode(raw: str) -> dict[str, Any] | None:
        try:
            entry = json.loads(raw)
        except (TypeError, ValueError):
            return None
        payload = entry.get("payload") if isinstance(entry, dict) else None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _decorate(
        payload: dict[str, Any], kind: str, similarity: float
    ) -> dict[str, Any]:
        out = dict(payload)
        out["cached"] = True
        out["cache_kind"] = kind
        out["cache_similarity"] = round(float(similarity), 4)
        return out

    def info(self) -> dict[str, Any]:
        client = self._redis_client()
        with self._lock:
            entries = len(self._vectors)
        return {
            "enabled": ENABLED,
            "backend": "redis" if client is not None else "local",
            "semantic": SEMANTIC,
            "threshold": THRESHOLD,
            "ttl_s": TTL,
            "fingerprint": corpus_fingerprint()[:16],
            "fingerprint_ttl_s": FINGERPRINT_TTL,
            "entries": entries,
            "max_entries": MAX_ENTRIES,
        }

    def render_metrics(self) -> list[str]:
        counts = self.stats()
        with self._lock:
            entries = len(self._vectors)
        backend = 1 if self._redis_client() is not None else 0
        return [
            "# HELP mingli_semcache_hits_total 语义缓存命中次数",
            "# TYPE mingli_semcache_hits_total counter",
            'mingli_semcache_hits_total{kind="exact"} %d' % counts["exact"],
            'mingli_semcache_hits_total{kind="semantic"} %d' % counts["semantic"],
            "# HELP mingli_semcache_misses_total 语义缓存未命中次数",
            "# TYPE mingli_semcache_misses_total counter",
            "mingli_semcache_misses_total %d" % counts["miss"],
            "# HELP mingli_semcache_stores_total 写入缓存次数",
            "# TYPE mingli_semcache_stores_total counter",
            "mingli_semcache_stores_total %d" % counts["store"],
            "# HELP mingli_semcache_errors_total 缓存降级次数",
            "# TYPE mingli_semcache_errors_total counter",
            "mingli_semcache_errors_total %d" % counts["error"],
            "# HELP mingli_semcache_entries 本进程向量索引条目数",
            "# TYPE mingli_semcache_entries gauge",
            "mingli_semcache_entries %d" % entries,
            "# HELP mingli_semcache_backend 缓存后端（1=redis，0=local）",
            "# TYPE mingli_semcache_backend gauge",
            "mingli_semcache_backend %d" % backend,
        ]

    # --- 测试 ---

    def reset(self) -> None:
        self._local.clear()
        with self._lock:
            self._vectors.clear()
            for key in self._counts:
                self._counts[key] = 0
        self._redis = None
        self._redis_broken = False


_cache: SemanticCache | None = None


def get_cache() -> SemanticCache:
    global _cache
    if _cache is None:
        _cache = SemanticCache()
    return _cache


def lookup(question: str, mode: str = "rag", top_k: int = 5):
    return get_cache().check(question, mode=mode, top_k=top_k)


def remember(
    question: str,
    mode: str,
    top_k: int,
    result: dict[str, Any],
    query_vec: np.ndarray | None = None,
) -> bool:
    return get_cache().remember(question, mode, top_k, result, query_vec=query_vec)


def info() -> dict[str, Any]:
    return get_cache().info()


def render_metrics() -> list[str]:
    return get_cache().render_metrics()


def reset_for_tests() -> None:
    global _cache, _ENCODER
    _cache = None
    _ENCODER = None
    # 指纹缓存和注入的 provider 也要清掉，避免测试之间串指纹。
    global _fingerprint_cache, _fingerprint_provider
    with _fingerprint_lock:
        _fingerprint_cache = None
        _fingerprint_provider = None
    # 配置可能在测试里被 monkeypatch，这里一起还原到环境默认
    global ENABLED, SEMANTIC, THRESHOLD, TTL, MAX_ENTRIES, FINGERPRINT_TTL
    ENABLED = os.environ.get("MINGLI_CACHE_ENABLED", "1") != "0"
    SEMANTIC = os.environ.get("MINGLI_CACHE_SEMANTIC", "1") != "0"
    THRESHOLD = float(os.environ.get("MINGLI_CACHE_THRESHOLD", "0.95"))
    TTL = float(os.environ.get("MINGLI_CACHE_TTL", "86400"))
    MAX_ENTRIES = int(os.environ.get("MINGLI_CACHE_MAX_ENTRIES", "1000"))
    FINGERPRINT_TTL = float(os.environ.get("MINGLI_CACHE_FINGERPRINT_TTL", "30"))
