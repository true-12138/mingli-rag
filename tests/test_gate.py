# -*- coding: utf-8 -*-
"""全局闸门测试：进程内兜底、Redis 原子语义、额度计数、Postgres 连接池配置。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import gate


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("MINGLI_REDIS_URL", raising=False)
    gate.reset_for_tests()
    yield
    gate.reset_for_tests()


def test_local_gate_limits_and_releases():
    g = gate.LocalGate()
    tokens = [g.try_acquire("answer", 2, 10) for _ in range(2)]
    assert all(tokens)
    assert g.try_acquire("answer", 2, 10) is None
    assert g.active("answer") == 2

    g.release("answer", tokens[0])
    assert g.active("answer") == 1
    assert g.try_acquire("answer", 2, 10)


def test_local_gate_expires_stale_slots():
    g = gate.LocalGate()
    token = g.try_acquire("answer", 1, ttl=0.01)
    assert token
    import time

    time.sleep(0.03)
    assert g.active("answer") == 0
    assert g.try_acquire("answer", 1, 10)


def test_denied_calls_are_counted():
    g = gate.LocalGate()
    assert g.try_acquire("answer", 1, 10)
    assert g.try_acquire("answer", 1, 10) is None
    snap = gate.STATS.snapshot()
    assert snap["granted"] == 1
    assert snap["denied"] == 1


def test_quota_disabled_by_default():
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.delenv("MINGLI_USER_DAILY_LIMIT", raising=False)
    try:
        ok, used = gate.take_quota("anon")
        assert ok and used == 0
        assert gate.quota_remaining("anon") is None
    finally:
        monkeypatch.undo()


def test_quota_counts_and_rejects_over_limit(monkeypatch):
    monkeypatch.setenv("MINGLI_USER_DAILY_LIMIT", "2")
    gate.reset_for_tests()
    assert gate.take_quota("a") == (True, 1)
    assert gate.take_quota("a") == (True, 2)
    ok, used = gate.take_quota("a")
    assert not ok and used == 3
    assert gate.quota_remaining("a") == 0
    # 不同用户互不影响
    assert gate.take_quota("b") == (True, 1)


def test_redis_gate_is_atomic_with_fakeredis(monkeypatch):
    fakeredis = pytest.importorskip("fakeredis")
    import redis

    fake = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(
        redis.Redis, "from_url", classmethod(lambda cls, *a, **kw: fake)
    )
    g = gate.RedisGate("redis://localhost:6379/0")
    assert g.backend == "redis"
    tokens = [g.try_acquire("answer", 2, 10) for _ in range(2)]
    assert all(tokens)
    assert g.try_acquire("answer", 2, 10) is None
    assert g.active("answer") == 2
    g.release("answer", tokens[0])
    assert g.active("answer") == 1


def test_redis_counter_uses_redis(monkeypatch):
    fakeredis = pytest.importorskip("fakeredis")
    import redis

    fake = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(
        redis.Redis, "from_url", classmethod(lambda cls, *a, **kw: fake)
    )
    g = gate.RedisGate("redis://localhost:6379/0")
    assert g.incr("quota:2026-11-07:u", 60) == 1
    assert g.incr("quota:2026-11-07:u", 60) == 2
    assert g.get("quota:2026-11-07:u") == 2


def test_postgres_url_is_normalized_to_psycopg():
    from db.base import normalize_db_url

    assert normalize_db_url("postgres://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert normalize_db_url("postgresql://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert normalize_db_url("sqlite://") == "sqlite://"


def test_postgres_engine_has_bounded_pool(monkeypatch):
    pytest.importorskip("psycopg")
    from db.base import make_engine

    monkeypatch.setenv("MINGLI_DB_POOL_SIZE", "17")
    monkeypatch.setenv("MINGLI_DB_MAX_OVERFLOW", "3")
    engine = make_engine("postgresql+psycopg://u:p@127.0.0.1:1/db")
    try:
        assert engine.pool.size() == 17
        assert engine.pool._max_overflow == 3
    finally:
        engine.dispose()
