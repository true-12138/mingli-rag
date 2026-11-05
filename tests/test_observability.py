# -*- coding: utf-8 -*-
"""可观测性测试：request id 透传、/metrics 内容。不调模型、不联网。"""
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import api
from observability import METRICS


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.delenv("MINGLI_API_TOKEN", raising=False)
    METRICS.reset()
    with TestClient(api.app) as test_client:
        yield test_client
    METRICS.reset()


def test_echoes_client_request_id(client):
    r = client.get("/health", headers={"X-Request-Id": "abc-123"})
    assert r.status_code == 200
    assert r.headers["x-request-id"] == "abc-123"


def test_generates_request_id_when_absent(client):
    r = client.get("/health")
    assert re.fullmatch(r"[0-9a-f]{16}", r.headers["x-request-id"])


def test_replaces_unsafe_request_id(client):
    r = client.get("/health", headers={"X-Request-Id": "bad id!"})
    assert r.headers["x-request-id"] != "bad id!"
    assert re.fullmatch(r"[0-9a-f]{16}", r.headers["x-request-id"])


def test_metrics_expose_counts_and_histogram(client):
    client.get("/health")
    body = client.get("/metrics").text
    assert 'mingli_http_requests_total{method="GET",path="/health",status="200"} 1' in body
    assert 'mingli_http_request_duration_seconds_count{method="GET",path="/health"}' in body
    assert "mingli_http_inflight 1" in body  # 渲染时本请求还在途
    # 请求结束后在途数必须回到 0，否则中间件的计数会越漏越多
    assert METRICS.inflight == 0


def test_metrics_uses_route_template_not_raw_path(client):
    """动态路由不能按原始 URL 打标签，否则标签基数会无限增长。"""
    client.get("/trace/not-exist")
    body = client.get("/metrics").text
    assert 'path="/trace/{trace_id}"' in body
    assert "not-exist" not in body


def test_metrics_is_plain_text(client):
    r = client.get("/metrics")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
