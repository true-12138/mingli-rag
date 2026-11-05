# -*- coding: utf-8 -*-
"""每日额度的原子性、退回与 HTTP 映射。

额度是成本闸门：并发下多放行一次就是真金白银，所以这里重点测
「50 个并发只放行额度内数量」「失败请求退回额度」「重启不清零」。
"""
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import requests
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import api
import quotas
from db.base import Base, make_engine


@pytest.fixture()
def session_factory(tmp_path, monkeypatch):
    """每个用例一份文件 SQLite；内存库在并发下只有一个连接，测不出竞争。"""
    engine = make_engine("sqlite:///" + (tmp_path / "quota.sqlite3").as_posix())
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(quotas, "SessionLocal", factory)
    yield factory
    engine.dispose()


def _limits(monkeypatch, *, user: int = 10, ip: int = 10, total: int = 10) -> None:
    monkeypatch.setenv("MINGLI_QUOTA_ENABLED", "1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "server-key")
    monkeypatch.setenv("MINGLI_QUOTA_USER_DAILY", str(user))
    monkeypatch.setenv("MINGLI_QUOTA_IP_DAILY", str(ip))
    monkeypatch.setenv("MINGLI_QUOTA_GLOBAL_DAILY", str(total))


def _rows(factory) -> dict[str, int]:
    with factory() as session:
        return {row.bucket: row.used for row in session.query(quotas.QuotaUsage)}


def test_user_limit_is_enforced(session_factory, monkeypatch):
    _limits(monkeypatch, user=1, ip=10, total=10)

    assert quotas.consume("anon-1", "1.1.1.1") is not None
    with pytest.raises(quotas.QuotaExceeded) as exc:
        quotas.consume("anon-1", "1.1.1.1")

    assert exc.value.bucket == "user:anon-1"
    assert exc.value.retry_after >= 1
    assert _rows(session_factory) == {
        "user:anon-1": 1,
        "ip:1.1.1.1": 1,
        "global": 1,
    }


def test_ip_denial_refunds_previously_reserved_user_bucket(session_factory, monkeypatch):
    _limits(monkeypatch, user=10, ip=1, total=10)

    assert quotas.consume("anon-1", "1.1.1.1") is not None
    with pytest.raises(quotas.QuotaExceeded) as exc:
        quotas.consume("anon-2", "1.1.1.1")

    assert exc.value.bucket == "ip:1.1.1.1"
    # anon-2 的用户额度已经退回，不能因为「IP 满了」就白扣一次
    rows = _rows(session_factory)
    assert rows["user:anon-2"] == 0
    assert rows["global"] == 1


def test_global_denial_refunds_user_and_ip(session_factory, monkeypatch):
    _limits(monkeypatch, user=10, ip=10, total=1)

    assert quotas.consume("anon-1", "1.1.1.1") is not None
    with pytest.raises(quotas.QuotaExceeded) as exc:
        quotas.consume("anon-2", "2.2.2.2")

    assert exc.value.bucket == "global"
    rows = _rows(session_factory)
    assert rows["global"] == 1
    assert rows["user:anon-2"] == 0
    assert rows["ip:2.2.2.2"] == 0


def test_counts_survive_new_session(session_factory, monkeypatch):
    _limits(monkeypatch, user=2, ip=10, total=10)
    assert quotas.consume("anon-1", "1.1.1.1") is not None
    # 每次 consume 都新开 session；第二次仍看得到上一次的计数（进程重启同理）
    assert quotas.consume("anon-1", "1.1.1.1") is not None
    with pytest.raises(quotas.QuotaExceeded):
        quotas.consume("anon-1", "1.1.1.1")


def test_refund_returns_the_whole_reservation(session_factory, monkeypatch):
    _limits(monkeypatch, user=1, ip=1, total=1)
    reservation = quotas.consume("anon-1", "1.1.1.1")
    assert reservation is not None

    quotas.refund(reservation)

    assert all(used == 0 for used in _rows(session_factory).values())
    assert quotas.consume("anon-1", "1.1.1.1") is not None


def test_visitor_key_and_missing_server_key_are_not_counted(session_factory, monkeypatch):
    _limits(monkeypatch, user=0, ip=0, total=0)
    assert quotas.consume("anon-1", "1.1.1.1", visitor_key="sk-visitor") is None

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert quotas.consume("anon-1", "1.1.1.1") is None
    assert _rows(session_factory) == {}


def test_fifty_concurrent_requests_only_admit_global_limit(session_factory, monkeypatch):
    _limits(monkeypatch, user=100, ip=100, total=10)
    workers = 50
    barrier = threading.Barrier(workers)

    def worker(index: int) -> bool:
        barrier.wait(timeout=10)
        try:
            quotas.consume("u{}".format(index), "10.0.0.{}".format(index))
            return True
        except quotas.QuotaExceeded:
            return False

    with ThreadPoolExecutor(max_workers=workers) as pool:
        admitted = list(pool.map(worker, range(workers)))

    assert sum(admitted) == 10
    assert _rows(session_factory)["global"] == 10


def test_chat_returns_429_with_retry_after(session_factory, monkeypatch):
    _limits(monkeypatch, user=1, ip=100, total=100)
    monkeypatch.setattr(
        api.rag, "answer",
        lambda *args, **kwargs: {"answer": "ok", "can_answer": True},
    )
    client = TestClient(api.app)
    headers = {"X-Anonymous-Id": "quota-user"}

    assert client.post("/chat", json={"question": "q"}, headers=headers).status_code == 200
    response = client.post("/chat", json={"question": "q"}, headers=headers)

    assert response.status_code == 429
    assert int(response.headers["retry-after"]) >= 1
    assert response.headers["x-quota-remaining"] == "0"


def test_failed_generation_refunds_quota(session_factory, monkeypatch):
    _limits(monkeypatch, user=1, ip=100, total=100)

    def upstream_failure(*args, **kwargs):
        raise requests.HTTPError("upstream 500")

    monkeypatch.setattr(api.rag, "answer", upstream_failure)
    client = TestClient(api.app)
    headers = {"X-Anonymous-Id": "failing-user"}

    assert client.post("/chat", json={"question": "q"}, headers=headers).status_code == 502
    # 第一次已经退回额度，第二次仍应走到上游（502），而不是被额度挡成 429
    assert client.post("/chat", json={"question": "q"}, headers=headers).status_code == 502
    assert all(used == 0 for used in _rows(session_factory).values())
