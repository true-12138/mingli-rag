# -*- coding: utf-8 -*-
"""自动断句：只许插标点，不许改字。

重点测「改字就作废」这条底线，以及缓存按原文内容去重。
不调模型；API 用例只验证路由与缓存命中时不占模型调用。
"""
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import api
import gate
import segment


SOURCE = "甲子乙丑海中金丙寅丁卯炉中火戊辰己巳大林木"
PUNCTUATED = "甲子乙丑，海中金。丙寅丁卯，炉中火。戊辰己巳，大林木。"


def _chunks(text=SOURCE):
    return [{"chunk_id": 21, "text": text}]


def test_same_content_ignores_punctuation_and_whitespace():
    assert segment.same_content(SOURCE, PUNCTUATED)
    assert segment.same_content(SOURCE, "甲子乙丑 海中金\n丙寅丁卯 炉中火\n戊辰己巳 大林木")
    assert not segment.same_content(SOURCE, PUNCTUATED.replace("炉", "炉中"))


def test_miss_then_cache_hit(tmp_path, monkeypatch):
    cache_file = tmp_path / "segment_cache.jsonl"
    monkeypatch.setenv("MINGLI_SEGMENT_CACHE", str(cache_file))
    calls = []

    def fake_punctuate(text, api_key=None):
        calls.append((text, api_key))
        return PUNCTUATED

    monkeypatch.setattr(segment, "punctuate", fake_punctuate)

    items, misses = segment.prepare(_chunks())
    assert items[0]["text"] is None
    assert len(misses) == 1
    segment.fill(items, misses, api_key="sk-should-not-be-written")
    assert items[0]["text"] == PUNCTUATED
    assert len(calls) == 1

    items2, misses2 = segment.prepare(_chunks())
    assert misses2 == []
    assert items2[0]["cached"] is True
    assert items2[0]["text"] == PUNCTUATED
    assert len(calls) == 1, "第二次不该再调模型"

    raw = cache_file.read_text(encoding="utf-8")
    assert "sk-should-not-be-written" not in raw
    row = json.loads(raw.strip().splitlines()[0])
    assert set(row) == {"key", "chunk_id", "version", "text"}


def test_invalid_cached_entry_is_not_served(tmp_path, monkeypatch):
    """缓存里混进改过字的结果时不能原样返回，要当作未命中重做。"""
    cache_file = tmp_path / "segment_cache.jsonl"
    monkeypatch.setenv("MINGLI_SEGMENT_CACHE", str(cache_file))
    cache_file.write_text(json.dumps({
        "key": segment._key(SOURCE), "chunk_id": 21,
        "version": segment.CACHE_VERSION,
        "text": "甲子乙丑，海中金。丙寅丁卯，炉中火。戊辰己巳，大森林。",
    }, ensure_ascii=False) + "\n", encoding="utf-8")

    items, misses = segment.prepare(_chunks())
    assert items[0]["text"] is None
    assert len(misses) == 1


def test_too_long_text_is_left_alone(tmp_path, monkeypatch):
    """超长不截断——截断后补的句读会对不齐原文，比不断句更糟。"""
    monkeypatch.setenv("MINGLI_SEGMENT_CACHE", str(tmp_path / "c.jsonl"))
    text = "甲" * (segment.MAX_CHARS + 1)
    items, misses = segment.prepare(_chunks(text))
    assert misses == []
    assert items[0]["text"] is None
    assert "过长" in items[0]["error"]


def test_punctuate_rejects_unchanged_text(monkeypatch):
    """字没变但一个标点也没加，等于没做；实测《钦定协纪辨方书》整段照抄。"""
    long_source = SOURCE + "庚午辛未路旁土壬申癸酉剑锋金甲戌乙亥山头火"
    monkeypatch.setattr(
        segment.rag, "_chat",
        lambda messages, api_key=None: json.dumps({"text": long_source}, ensure_ascii=False),
    )
    with pytest.raises(segment.SegmentMismatch):
        segment.punctuate(long_source)


def test_punctuate_rejects_changed_characters(monkeypatch):
    monkeypatch.setattr(
        segment.rag, "_chat",
        lambda messages, api_key=None: json.dumps(
            {"text": "甲子乙丑，海中金。丙寅丁卯，炉中火。戊辰己巳，大森林。"},
            ensure_ascii=False),
    )
    with pytest.raises(segment.SegmentMismatch):
        segment.punctuate(SOURCE)


def test_punctuate_retries_once_when_characters_change(monkeypatch):
    calls = []

    def fake_chat(messages, api_key=None):
        calls.append(messages)
        if len(calls) == 1:
            return json.dumps({"text": "甲子乙丑，海中金。丙寅丁卯，炉中火。戊辰己巳，大森林。"},
                              ensure_ascii=False)
        assert "不能改动" in messages[-1]["content"]
        return json.dumps({"text": PUNCTUATED}, ensure_ascii=False)

    monkeypatch.setattr(segment.rag, "_chat", fake_chat)
    assert segment.punctuate(SOURCE) == PUNCTUATED
    assert len(calls) == 2


def test_punctuate_accepts_space_removal(monkeypatch):
    """无标点组有全角空格占位；模型去掉空格不算改字。"""
    monkeypatch.setattr(
        segment.rag, "_chat",
        lambda messages, api_key=None: json.dumps(
            {"text": "甲子乙丑，海中金。丙寅丁卯，炉中火。戊辰己巳，大林木。"},
            ensure_ascii=False),
    )
    assert segment.punctuate("甲子乙丑　海中金　丙寅丁卯　炉中火　戊辰己巳　大林木").startswith("甲子")


def test_retry_can_be_disabled(monkeypatch):
    monkeypatch.setenv("MINGLI_SEGMENT_RETRY", "0")
    calls = []

    def fake_chat(messages, api_key=None):
        calls.append(1)
        return json.dumps({"text": "改过的字"}, ensure_ascii=False)

    monkeypatch.setattr(segment.rag, "_chat", fake_chat)
    with pytest.raises(segment.SegmentMismatch):
        segment.punctuate(SOURCE)
    assert len(calls) == 1


def test_fill_marks_mismatch_without_caching(tmp_path, monkeypatch):
    monkeypatch.setenv("MINGLI_SEGMENT_CACHE", str(tmp_path / "c.jsonl"))

    def bad(text, api_key=None):
        raise segment.SegmentMismatch("补句读时改动或增删了原文的字")

    monkeypatch.setattr(segment, "punctuate", bad)
    items, misses = segment.prepare(_chunks())
    segment.fill(items, misses)
    assert items[0]["text"] is None
    assert "改动了原文的字" in items[0]["error"]
    assert segment.cache_path().exists() is False


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.delenv("MINGLI_API_TOKEN", raising=False)
    monkeypatch.delenv("MINGLI_REDIS_URL", raising=False)
    gate.reset_for_tests()
    yield TestClient(api.app)
    gate.reset_for_tests()


def test_endpoint_rejects_more_than_four_ids(client):
    r = client.post("/v1/chunks/segment", json={"ids": [1, 2, 3, 4, 5]})
    assert r.status_code == 422


def test_endpoint_cached_path_does_not_touch_model(client, monkeypatch):
    monkeypatch.setattr(
        api, "_chunk_index",
        lambda: {7: {"chunk_id": 7, "chunk_text": SOURCE}},
    )
    monkeypatch.setattr(
        api.segment, "prepare",
        lambda chunks, force=False: ([{
            "chunk_id": 7, "text": PUNCTUATED, "cached": True, "error": None,
        }], []),
    )
    called = {"fill": 0}
    monkeypatch.setattr(api.segment, "fill", lambda *a, **k: called.__setitem__("fill", 1))

    r = client.post("/v1/chunks/segment", json={"ids": [7]})
    assert r.status_code == 200
    data = r.json()
    assert data["items"][0]["cached"] is True
    assert data["items"][0]["text"] == PUNCTUATED
    assert called["fill"] == 0, "全命中缓存时不该进模型调用"
