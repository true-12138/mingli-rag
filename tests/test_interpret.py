# -*- coding: utf-8 -*-
"""解读层：白话释义的缓存、截断与「译文不是证据」的边界。

不加载检索索引、不调模型；API 用例只验证路由与缓存命中时不占模型调用。
"""
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import api
import gate
import interpret


def _chunks(text="正官者，乃甲见辛之类，阴阳相配，故为正。"):
    return [{"chunk_id": 11, "text": text}]


def test_miss_then_cache_hit(tmp_path, monkeypatch):
    """同一段原文第二次展开不再调模型，且缓存文件里不出现任何 key。"""
    cache_file = tmp_path / "interpret_cache.jsonl"
    monkeypatch.setenv("MINGLI_INTERPRET_CACHE", str(cache_file))
    calls = []

    def fake_translate(text, api_key=None):
        calls.append((text, api_key))
        return "正官，就是甲木见辛金一类，阴阳相配，所以叫正官。"

    monkeypatch.setattr(interpret, "translate", fake_translate)

    items, misses = interpret.prepare(_chunks())
    assert items[0]["translation"] is None
    assert len(misses) == 1
    interpret.fill(items, misses, api_key="sk-should-not-be-written")
    assert items[0]["translation"].startswith("正官")
    assert len(calls) == 1

    items2, misses2 = interpret.prepare(_chunks())
    assert misses2 == []
    assert items2[0]["cached"] is True
    assert items2[0]["translation"] == items[0]["translation"]
    assert len(calls) == 1, "第二次不该再调模型"

    raw = cache_file.read_text(encoding="utf-8")
    assert "sk-should-not-be-written" not in raw
    row = json.loads(raw.strip().splitlines()[0])
    assert set(row) == {"key", "chunk_id", "version", "translation"}


def test_cached_copy_is_not_served(tmp_path, monkeypatch):
    """规则上线前缓存下来的「照搬译文」不能再原样返回，要当作未命中重译。"""
    cache_file = tmp_path / "interpret_cache.jsonl"
    monkeypatch.setenv("MINGLI_INTERPRET_CACHE", str(cache_file))
    text = _chunks()[0]["text"]
    cache_file.write_text(json.dumps({
        "key": interpret._key(text), "chunk_id": 11,
        "version": interpret.CACHE_VERSION, "translation": text,
    }, ensure_ascii=False) + "\n", encoding="utf-8")

    items, misses = interpret.prepare(_chunks())
    assert items[0]["translation"] is None
    assert len(misses) == 1, "照搬的旧译文应视为未命中"

    monkeypatch.setenv("MINGLI_INTERPRET_CHECK", "0")
    items2, misses2 = interpret.prepare(_chunks())
    assert items2[0]["cached"] is True, "关掉检查时保持旧的缓存行为"


def test_force_bypasses_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("MINGLI_INTERPRET_CACHE", str(tmp_path / "c.jsonl"))
    monkeypatch.setattr(interpret, "translate", lambda text, api_key=None: "译文")
    items, misses = interpret.prepare(_chunks())
    interpret.fill(items, misses)

    items2, misses2 = interpret.prepare(_chunks(), force=True)
    assert len(misses2) == 1, "force=True 应重新生成"


def test_long_text_is_truncated_but_cached_under_full_text(tmp_path, monkeypatch):
    monkeypatch.setenv("MINGLI_INTERPRET_CACHE", str(tmp_path / "c.jsonl"))
    text = "甲" * (interpret.MAX_CHARS + 50)
    seen = {}

    def fake_translate(body, api_key=None):
        seen["body"] = body
        return "略"

    monkeypatch.setattr(interpret, "translate", fake_translate)
    items, misses = interpret.prepare(_chunks(text))
    assert items[0]["truncated"] is True
    interpret.fill(items, misses)
    assert len(seen["body"]) == interpret.MAX_CHARS

    items2, misses2 = interpret.prepare(_chunks(text))
    assert misses2 == [], "截断后的译文应按完整原文的 key 命中"
    assert items2[0]["cached"] is True


def test_translate_rejects_non_translation(monkeypatch):
    """模型把「讲解」当译文返回时要报错，不能把它混进阅读区。"""
    monkeypatch.setattr(interpret.rag, "_chat", lambda messages, api_key=None: '{"translation": ""}')
    assert interpret.translate("原文") == "", "空译文表示无法成句对译"

    monkeypatch.setattr(interpret.rag, "_chat", lambda messages, api_key=None: '{"note": "没有这个字段"}')
    with pytest.raises(ValueError):
        interpret.translate("原文")

    too_long = json.dumps({"translation": "长" * 700}, ensure_ascii=False)
    monkeypatch.setattr(interpret.rag, "_chat", lambda messages, api_key=None: too_long)
    with pytest.raises(ValueError):
        interpret.translate("短")


def test_fill_records_per_item_error(tmp_path, monkeypatch):
    """一条失败只标在那一段上，其他引用仍能读。"""
    monkeypatch.setenv("MINGLI_INTERPRET_CACHE", str(tmp_path / "c.jsonl"))

    def flaky(text, api_key=None):
        raise RuntimeError("上游 500")

    monkeypatch.setattr(interpret, "translate", flaky)
    items, misses = interpret.prepare(_chunks())
    interpret.fill(items, misses)
    assert items[0]["translation"] is None
    assert "释义生成失败" in items[0]["error"]


def test_fill_marks_copy_as_untranslatable(tmp_path, monkeypatch):
    """模型照搬原文时给「无法对译」，不要把照搬失败说成上游故障。"""
    monkeypatch.setenv("MINGLI_INTERPRET_CACHE", str(tmp_path / "c.jsonl"))

    def copy(text, api_key=None):
        raise interpret.CopyNotTranslated("模型没有真正翻译（照搬原文）")

    monkeypatch.setattr(interpret, "translate", copy)
    items, misses = interpret.prepare(_chunks())
    interpret.fill(items, misses)
    assert items[0]["translation"] is None
    assert items[0]["error"] == "这段原文暂时无法对译，可用原文阅读"
    assert interpret.cache_path().exists() is False


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.delenv("MINGLI_API_TOKEN", raising=False)
    monkeypatch.delenv("MINGLI_REDIS_URL", raising=False)
    gate.reset_for_tests()
    yield TestClient(api.app)
    gate.reset_for_tests()


def test_endpoint_rejects_more_than_four_ids(client):
    r = client.post("/v1/chunks/interpret", json={"ids": [1, 2, 3, 4, 5]})
    assert r.status_code == 422


def test_endpoint_cached_path_does_not_touch_model(client, monkeypatch):
    monkeypatch.setattr(
        api, "_chunk_index",
        lambda: {7: {"chunk_id": 7, "chunk_text": "月令者，提纲之谓也。"}},
    )
    monkeypatch.setattr(
        api.interpret, "prepare",
        lambda chunks, force=False: ([{
            "chunk_id": 7, "translation": "月令，就是提纲的意思。",
            "cached": True, "truncated": False, "error": None,
        }], []),
    )
    called = {"fill": 0}
    monkeypatch.setattr(api.interpret, "fill", lambda *a, **k: called.__setitem__("fill", 1))

    r = client.post("/v1/chunks/interpret", json={"ids": [7]})
    assert r.status_code == 200
    data = r.json()
    assert data["items"][0]["cached"] is True
    assert data["items"][0]["translation"].startswith("月令")
    assert called["fill"] == 0, "全命中缓存时不该进模型调用"


def test_endpoint_miss_goes_through_fill(client, monkeypatch):
    monkeypatch.setattr(
        api, "_chunk_index",
        lambda: {7: {"chunk_id": 7, "chunk_text": "月令者，提纲之谓也。"}},
    )
    item = {"chunk_id": 7, "translation": None, "cached": False,
            "truncated": False, "error": None}
    monkeypatch.setattr(
        api.interpret, "prepare",
        lambda chunks, force=False: ([item], [(item, "月令者，提纲之谓也。", "k")]),
    )

    def fake_fill(items, misses, api_key=None):
        items[0]["translation"] = "月令，就是提纲的意思。"

    monkeypatch.setattr(api.interpret, "fill", fake_fill)
    gate.reset_for_tests()

    r = client.post("/v1/chunks/interpret", json={"ids": [7]})
    assert r.status_code == 200
    assert r.json()["items"][0]["translation"].startswith("月令")
