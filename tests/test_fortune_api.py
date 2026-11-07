# -*- coding: utf-8 -*-
"""排盘接口测试：只搭排盘 router，不加载语料和 embedding。

重点验证三件事：
1. 排盘确定性——同样输入永远同一个盘；
2. 塔罗 seed 会回给前端，`/read` 必须用同一个 seed 重算；
3. `/read` 不接受前端塞进来的盘，只按 params 重算。
"""
import sys
from pathlib import Path

import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import api_fortune
from fortune.astro import SIGNS


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.delenv("MINGLI_API_TOKEN", raising=False)
    app = FastAPI()
    app.include_router(api_fortune.router)
    return TestClient(app)


BAZI = {"year": 1995, "month": 8, "day": 20, "hour": 14, "minute": 30, "gender": "male"}
ASTRO = {**BAZI, "tz": 8.0, "lat": 39.9, "lon": 116.4, "city": "北京"}


def test_bazi_chart_is_deterministic(client):
    first = client.post("/v1/fortune/bazi", json=BAZI)
    assert first.status_code == 200, first.text
    chart = first.json()
    assert chart["kind"] == "bazi"
    assert set(chart["sizhu"]) == {"年柱", "月柱", "日柱", "时柱"}
    assert sum(chart["wuxing"].values()) == 8
    assert chart["text"].startswith("公历")
    assert len(chart["dayun"]) >= 1

    second = client.post("/v1/fortune/bazi", json=BAZI).json()
    assert second["sizhu"] == chart["sizhu"]
    assert second["dayun"] == chart["dayun"]


def test_bazi_rejects_impossible_date(client):
    bad = {**BAZI, "month": 2, "day": 30}
    r = client.post("/v1/fortune/bazi", json=bad)
    assert r.status_code == 400
    assert "不合法" in r.json()["detail"]


def test_bazi_field_range_is_validated(client):
    r = client.post("/v1/fortune/bazi", json={**BAZI, "hour": 24})
    assert r.status_code == 422


def test_astro_chart_has_planets_houses_and_angles(client):
    r = client.post("/v1/fortune/astro", json=ASTRO)
    assert r.status_code == 200, r.text
    chart = r.json()
    assert len(chart["planets"]) == 10
    assert len(chart["houses"]) == 12
    assert chart["asc"]["sign"] in SIGNS
    assert chart["house_system"] == "整宫制"
    assert "上升" in chart["text"]


def test_tarot_seed_is_returned_and_reproducible(client):
    r = client.post("/v1/fortune/tarot", json={"spread": "three"})
    assert r.status_code == 200, r.text
    chart = r.json()
    assert chart["seed"] is not None
    assert [c["position"] for c in chart["cards"]] == ["过去", "现在", "未来"]

    again = client.post(
        "/v1/fortune/tarot", json={"spread": "three", "seed": chart["seed"]}
    ).json()
    assert again["cards"] == chart["cards"]


def test_tarot_invalid_spread_is_rejected(client):
    r = client.post("/v1/fortune/tarot", json={"spread": "horseshoe"})
    assert r.status_code == 422


def test_read_recomputes_chart_from_params(client, monkeypatch):
    captured = {}

    def fake_read(chart, question=None, user_note=None, temperature=0.7, api_key=None):
        captured["chart"] = chart
        captured["question"] = question
        captured["key"] = api_key
        return {
            "kind": chart["kind"],
            "summary": "测试解读",
            "sections": [{"title": "结构", "content": "内容"}],
            "disclaimer": "仅供文化参考",
            "parse_error": False,
        }

    monkeypatch.setattr(api_fortune.interpret, "read", fake_read)
    payload = {
        "kind": "tarot",
        # 前端塞一张假牌进来，服务端必须无视，按 params 重抽
        "params": {"spread": "single", "seed": 42},
        "question": "最近的工作方向？",
    }
    r = client.post(
        "/v1/fortune/read", json=payload, headers={"X-DeepSeek-Key": "sk-test"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["summary"] == "测试解读"
    chart = captured["chart"]
    assert chart["kind"] == "tarot"
    assert [c["position"] for c in chart["cards"]] == ["整体提示"]
    assert chart["seed"] == 42
    assert captured["question"] == "最近的工作方向？"
    assert captured["key"] == "sk-test"


def test_read_maps_missing_key_to_503(client, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("缺少 DEEPSEEK_API_KEY")

    monkeypatch.setattr(api_fortune.interpret, "read", boom)
    r = client.post(
        "/v1/fortune/read", json={"kind": "bazi", "params": BAZI}
    )
    assert r.status_code == 503


def test_read_maps_upstream_error_to_502(client, monkeypatch):
    def boom(*args, **kwargs):
        response = requests.Response()
        response.status_code = 429
        raise requests.HTTPError("rate limited", response=response)

    monkeypatch.setattr(api_fortune.interpret, "read", boom)
    r = client.post("/v1/fortune/read", json={"kind": "bazi", "params": BAZI})
    assert r.status_code == 502
    assert "429" in r.json()["detail"]


def test_bearer_token_is_enforced_when_configured(client, monkeypatch):
    monkeypatch.setenv("MINGLI_API_TOKEN", "secret")
    assert client.post("/v1/fortune/bazi", json=BAZI).status_code == 401
    ok = client.post(
        "/v1/fortune/bazi", json=BAZI, headers={"Authorization": "Bearer secret"}
    )
    assert ok.status_code == 200
