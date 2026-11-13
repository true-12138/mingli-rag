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
    assert [c["position"] for c in chart["cards"]] == ["背景", "当下", "可留意的方向"]

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


def test_intake_asks_for_missing_slots_without_guessing(client):
    """只说了年份：问清时辰和性别，不拿默认值把盘算出来。"""
    r = client.post("/v1/fortune/intake", json={
        "kind": "bazi", "params": {"year": 1995},
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "need_input"
    assert body["reason"] == "missing"
    assert body["known"] == {"year": 1995}
    assert [f["name"] for f in body["fields"]] == [
        "month", "day", "hour", "gender",
    ]
    assert "chart" not in body
    # 每个字段都要能直接渲染成追问：标签、类型、示例、问法
    month = body["fields"][0]
    assert month["label"] == "出生月份"
    assert month["type"] == "int" and month["min"] == 1
    assert month["ask"].endswith("（1–12）")


def test_intake_flags_bad_value_and_keeps_the_rest(client):
    r = client.post("/v1/fortune/intake", json={
        "kind": "bazi",
        "params": {"year": 1995, "month": 13, "day": 20, "hour": 14, "gender": "male"},
    })
    body = r.json()
    assert body["status"] == "need_input"
    assert body["reason"] == "invalid"
    assert [f["name"] for f in body["fields"]] == ["month"]
    assert body["fields"][0]["error"] == "不能大于 12"
    assert body["fields"][0]["value"] == 13
    # 合法的字段不会重复问
    assert body["known"]["hour"] == 14
    assert body["known"]["day"] == 20


def test_intake_ready_returns_chart_and_reports_defaults(client):
    r = client.post("/v1/fortune/intake", json={
        "kind": "astro",
        "params": {"year": 1995, "month": 8, "day": 20, "hour": 14},
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ready"
    assert body["chart"]["kind"] == "astro"
    assert body["params"]["minute"] == 0
    assert body["defaults"]["city"] == "北京"
    assert any("北京" in w for w in body["warnings"])


def test_intake_calendar_error_asks_again(client):
    """2 月 30 日能过单字段范围，但排盘函数会拒绝：这时重新问年月日。"""
    r = client.post("/v1/fortune/intake", json={
        "kind": "bazi",
        "params": {"year": 1995, "month": 2, "day": 30, "hour": 14, "gender": "male"},
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "need_input"
    assert body["reason"] == "calendar"
    assert "day" in [f["name"] for f in body["fields"]]
    assert "不合法" in body["message"]


def test_intake_ignores_display_only_keys(client):
    """把一张盘的 input 原样传回来也能用：solar/lunar 这类展示字段被忽略。"""
    r = client.post("/v1/fortune/intake", json={
        "kind": "bazi",
        "params": {**BAZI, "solar": "1995-08-20 14:30:00", "lunar": "七月廿五"},
    })
    body = r.json()
    assert body["status"] == "ready"
    assert sorted(body["ignored"]) == ["lunar", "solar"]
    assert body["chart"]["sizhu"] == client.post(
        "/v1/fortune/bazi", json=BAZI
    ).json()["sizhu"]


def test_intake_tarot_needs_nothing(client):
    body = client.post("/v1/fortune/intake", json={"kind": "tarot", "params": {}}).json()
    assert body["status"] == "ready"
    # seed 在这一步就固定下来，之后解读必须用这一组牌
    assert body["chart"]["seed"] is not None
    assert len(body["chart"]["cards"]) == 3


def test_intake_tarot_params_carry_the_seed_so_reuse_reproduces_cards(client):
    """intake 返回的 params 必须能原样喂回去：客户端照文档办事就该拿到同一组牌。"""
    first = client.post("/v1/fortune/intake", json={"kind": "tarot", "params": {}}).json()
    assert first["params"]["seed"] == first["chart"]["seed"]

    again = client.post("/v1/fortune/intake",
                        json={"kind": "tarot", "params": first["params"]}).json()
    assert again["chart"]["cards"] == first["chart"]["cards"]


def test_read_with_incomplete_params_returns_structured_400(client):
    r = client.post("/v1/fortune/read", json={
        "kind": "bazi", "params": {"year": 1995},
    })
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert detail["need_input"] is True
    assert [f["name"] for f in detail["fields"]] == [
        "month", "day", "hour", "gender",
    ]


def test_intake_rejects_unknown_kind(client):
    assert client.post(
        "/v1/fortune/intake", json={"kind": "ziwei", "params": {}}
    ).status_code == 422


def test_bearer_token_is_enforced_when_configured(client, monkeypatch):
    monkeypatch.setenv("MINGLI_API_TOKEN", "secret")
    assert client.post("/v1/fortune/bazi", json=BAZI).status_code == 401
    ok = client.post(
        "/v1/fortune/bazi", json=BAZI, headers={"Authorization": "Bearer secret"}
    )
    assert ok.status_code == 200
