# -*- coding: utf-8 -*-
"""全局并发闸门：多 worker / 多实例共享同一条容量线。

为什么需要它：进程内 `asyncio.Semaphore` 只能管住一个 worker。4 个 uvicorn
worker 各开 20 槽，实际就是 80 条并发回答，压测数据会失真，DeepSeek 也可能
被瞬间打满。这里把「回答槽」和「每用户额度」放到 Redis：

- 槽用 sorted set 存 `token -> 过期时间`，Lua 脚本原子地清理过期项、判满、
  占位。进程崩溃时槽会在 TTL 后自动回收，不会永久泄漏；
- 没配 `MINGLI_REDIS_URL` 时退化为进程内实现，本地开发、单测和没装 Redis 的
  环境照常跑。`/health` 会如实报告当前是 `redis` 还是 `local`。

语义保持「满了立刻 429」，不排队：SSE 的首 token 延迟比吞吐更重要。
"""
from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from typing import Any

logger = logging.getLogger("mingli.gate")

REDIS_URL = os.environ.get("MINGLI_REDIS_URL", "").strip()
KEY_PREFIX = os.environ.get("MINGLI_REDIS_PREFIX", "mingli")

# 一个回答最长可能跑多久。槽的 TTL 必须比它长；进程被杀时最多泄漏这么久。
ANSWER_SLOT_TTL = float(os.environ.get("MINGLI_ANSWER_SLOT_TTL", "300"))

# Lua：先清过期项，再判满，再占位。KEYS[1]=槽 key，ARGV=now/limit/ttl/token
_ACQUIRE_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local ttl = tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', key, '-inf', now)
if redis.call('ZCARD', key) >= limit then
  return 0
end
redis.call('ZADD', key, now + ttl, ARGV[4])
redis.call('PEXPIRE', key, math.floor(ttl * 1000) + 1000)
return 1
"""


class GateStats:
    """进程内统计；真正的全局数看 Redis。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.granted = 0
        self.denied = 0
        self.redis_errors = 0

    def record(self, granted: bool) -> None:
        with self._lock:
            if granted:
                self.granted += 1
            else:
                self.denied += 1

    def record_redis_error(self) -> None:
        with self._lock:
            self.redis_errors += 1

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                "granted": self.granted,
                "denied": self.denied,
                "redis_errors": self.redis_errors,
            }


STATS = GateStats()


class LocalGate:
    """进程内兜底实现，接口与 RedisGate 一致。"""

    backend = "local"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._slots: dict[str, dict[str, float]] = {}

    def _prune(self, name: str, now: float) -> dict[str, float]:
        bucket = self._slots.setdefault(name, {})
        for token, expires in list(bucket.items()):
            if expires <= now:
                bucket.pop(token, None)
        return bucket

    def try_acquire(self, name: str, limit: int, ttl: float) -> str | None:
        now = time.time()
        token = uuid.uuid4().hex
        with self._lock:
            bucket = self._prune(name, now)
            if len(bucket) >= limit:
                STATS.record(False)
                return None
            bucket[token] = now + ttl
        STATS.record(True)
        return token

    def release(self, name: str, token: str | None) -> None:
        if not token:
            return
        with self._lock:
            self._slots.get(name, {}).pop(token, None)

    def active(self, name: str) -> int:
        with self._lock:
            return len(self._prune(name, time.time()))


class RedisGate:
    """Redis 全局实现。同步调用，async 路径用 `to_thread` 包一层。"""

    backend = "redis"

    def __init__(self, url: str) -> None:
        import redis  # 延迟导入：没装驱动时还能走 LocalGate

        self._redis = redis.Redis.from_url(url, decode_responses=True, socket_timeout=2.0)
        self._fallback = LocalGate()
        self._script = self._redis.register_script(_ACQUIRE_LUA)
        # Redis 不可用时整段退化为本进程兜底，避免「占位走 Redis、查询走内存」
        self._degraded = False

    def _key(self, name: str) -> str:
        return "{}:gate:{}".format(KEY_PREFIX, name)

    def _on_error(self, exc: Exception) -> None:
        self._degraded = True
        STATS.record_redis_error()
        if STATS.snapshot()["redis_errors"] == 1:
            logger.warning("Redis 闸门不可用，退化为进程内限流：%s", exc)

    def try_acquire(self, name: str, limit: int, ttl: float) -> str | None:
        if self._degraded:
            return self._fallback.try_acquire(name, limit, ttl)
        token = uuid.uuid4().hex
        try:
            ok = self._script(
                keys=[self._key(name)],
                args=[time.time(), limit, ttl, token],
            )
        except Exception as exc:  # noqa: BLE001 - Redis 坏了不能拖垮整个服务
            self._on_error(exc)
            return self._fallback.try_acquire(name, limit, ttl)
        STATS.record(bool(ok))
        return token if ok else None

    def release(self, name: str, token: str | None) -> None:
        if not token:
            return
        if self._degraded:
            self._fallback.release(name, token)
            return
        try:
            self._redis.zrem(self._key(name), token)
        except Exception as exc:  # noqa: BLE001
            self._on_error(exc)
            self._fallback.release(name, token)

    def active(self, name: str) -> int:
        if self._degraded:
            return self._fallback.active(name)
        try:
            self._redis.zremrangebyscore(self._key(name), "-inf", time.time())
            return int(self._redis.zcard(self._key(name)))
        except Exception as exc:  # noqa: BLE001
            self._on_error(exc)
            return self._fallback.active(name)

    def incr(self, key: str, ttl: float) -> int:
        """固定窗口计数（额度用）。过期时间只在第一次设置，避免每次续期。"""
        if self._degraded:
            return -1
        full = "{}:{}".format(KEY_PREFIX, key)
        try:
            pipe = self._redis.pipeline()
            pipe.incr(full)
            pipe.expire(full, int(ttl), nx=True)
            value, _ = pipe.execute()
            return int(value)
        except Exception as exc:  # noqa: BLE001
            self._on_error(exc)
            return -1

    def get(self, key: str) -> int:
        if self._degraded:
            return -1
        try:
            return int(self._redis.get("{}:{}".format(KEY_PREFIX, key)) or 0)
        except Exception as exc:  # noqa: BLE001
            self._on_error(exc)
            return -1


class MemoryCounter:
    """额度计数的进程内兜底，按天过期。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[str, tuple[int, float]] = {}

    def _take(self, key: str, ttl: float) -> int:
        now = time.time()
        with self._lock:
            value, expires = self._items.get(key, (0, now + ttl))
            if expires <= now:
                value, expires = 0, now + ttl
            value += 1
            self._items[key] = (value, expires)
            return value

    def incr(self, key: str, ttl: float) -> int:
        return self._take(key, ttl)

    def get(self, key: str) -> int:
        with self._lock:
            value, expires = self._items.get(key, (0, 0))
            return value if expires > time.time() else 0


class Counter:
    """额度计数器门面：Redis 优先，失败/未配置走内存。"""

    def __init__(self, gate: LocalGate | RedisGate) -> None:
        self._gate = gate
        self._memory = MemoryCounter()

    def incr(self, key: str, ttl: float) -> int:
        if isinstance(self._gate, RedisGate):
            value = self._gate.incr(key, ttl)
            if value >= 0:
                return value
        return self._memory.incr(key, ttl)

    def get(self, key: str) -> int:
        if isinstance(self._gate, RedisGate):
            value = self._gate.get(key)
            if value >= 0:
                return value
        return self._memory.get(key)


_gate: LocalGate | RedisGate | None = None


def get_gate() -> LocalGate | RedisGate:
    global _gate
    if _gate is None:
        if REDIS_URL:
            try:
                _gate = RedisGate(REDIS_URL)
                logger.info("并发闸门使用 Redis：%s", REDIS_URL.split("@")[-1])
            except Exception as exc:  # noqa: BLE001
                STATS.record_redis_error()
                logger.warning("Redis 初始化失败，退化为进程内限流：%s", exc)
                _gate = LocalGate()
        else:
            _gate = LocalGate()
            logger.info("未配置 MINGLI_REDIS_URL，并发闸门使用进程内实现")
    return _gate


_counter: Counter | None = None


def get_counter() -> Counter:
    global _counter
    if _counter is None:
        _counter = Counter(get_gate())
    return _counter


def backend_name() -> str:
    return get_gate().backend


def reset_for_tests() -> None:
    """测试用：清掉单例与统计。"""
    global _gate, _counter
    _gate = None
    _counter = None
    STATS.__init__()


def render_metrics() -> list[str]:
    snap = STATS.snapshot()
    gate = get_gate()
    try:
        active = gate.active("answer")
    except Exception:  # noqa: BLE001
        active = -1
    return [
        "# HELP mingli_answer_slots_active 当前占用的回答槽（本进程视角）",
        "# TYPE mingli_answer_slots_active gauge",
        "mingli_answer_slots_active %d" % active,
        "# HELP mingli_gate_acquire_total 闸门放行/拒绝次数",
        "# TYPE mingli_gate_acquire_total counter",
        'mingli_gate_acquire_total{result="granted"} %d' % snap["granted"],
        'mingli_gate_acquire_total{result="denied"} %d' % snap["denied"],
        "# HELP mingli_gate_redis_errors_total Redis 闸门异常次数",
        "# TYPE mingli_gate_redis_errors_total counter",
        "mingli_gate_redis_errors_total %d" % snap["redis_errors"],
        "# HELP mingli_gate_backend 当前闸门后端（1=redis，0=local）",
        "# TYPE mingli_gate_backend gauge",
        "mingli_gate_backend %d" % (1 if gate.backend == "redis" else 0),
    ]


def answer_limit() -> int:
    return int(os.environ.get("MINGLI_ANSWER_SLOTS", "20"))


def quota_limit() -> int:
    """0 = 不启用每用户额度。"""
    return int(os.environ.get("MINGLI_USER_DAILY_LIMIT", "0"))


def quota_key(anonymous_id: str) -> str:
    return "quota:{}:{}".format(time.strftime("%Y-%m-%d"), anonymous_id)


def take_quota(anonymous_id: str) -> tuple[bool, int]:
    """占用一次每用户额度。返回 (是否放行, 已用次数)。"""
    limit = quota_limit()
    if limit <= 0:
        return True, 0
    used = get_counter().incr(quota_key(anonymous_id), ttl=86400 * 2)
    return used <= limit, used


def quota_remaining(anonymous_id: str) -> int | None:
    limit = quota_limit()
    if limit <= 0:
        return None
    return max(0, limit - get_counter().get(quota_key(anonymous_id)))


def info() -> dict[str, Any]:
    return {
        "backend": backend_name(),
        "redis_configured": bool(REDIS_URL),
        "answer_slots": answer_limit(),
        "user_daily_limit": quota_limit(),
    }
