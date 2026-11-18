# -*- coding: utf-8 -*-
"""`/v1/favorites` 接口测试：素材收藏 + Markdown 导出。

语料用一对假 chunk 替代：测试只关心「收藏只存 chunk_id、原文从语料取」这条线，
不验证语料本身；假数据也让导出文本可以逐字断言。
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import api
import materials
from db.base import Base, get_session, make_engine

CHUNK_A = {
    "chunk_text": "用神既得，格局自定。\n喜忌既定，岁运可知。",
    "meta": {
        "book": "子平真诠",
        "volume": "卷一",
        "chapter": "论用神",
        "line_start": 10,
        "line_end": 12,
        "sourcefile": "01_子平/标点组/子平真诠.txt",
    },
}
CHUNK_B = {
    "chunk_text": "命理之要，先看月令。",
    "meta": {
        "book": "滴天髓",
        "volume": "",
        "chapter": "通神论",
        "line_start": 3,
        "line_end": 3,
        "sourcefile": "02_命理/标点组/滴天髓.txt",
    },
}


@pytest.fixture()
def corpus(monkeypatch):
    """替换 materials 的语料索引（只替换查表，不改收藏/导出逻辑）。

    yield 出去后测试可以删 key，模拟语料重编号后旧的 chunk_id 指空。
    """
    index = {1: CHUNK_A, 2: CHUNK_B}
    monkeypatch.setattr(materials, "_INDEX", index)
    return index


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.delenv("MINGLI_API_TOKEN", raising=False)

    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, expire_on_commit=False)

    def override_session():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    api.app.dependency_overrides[get_session] = override_session
    with TestClient(api.app) as test_client:
        yield test_client
    api.app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


def _save(client, chunk_id=1, note=None, anon="anon-1"):
    payload = {"chunk_id": chunk_id}
    if note is not None:
        payload["note"] = note
    return client.post(
        "/v1/favorites", json=payload, headers={"X-Anonymous-Id": anon}
    )


def _list(client, anon="anon-1", **params):
    return client.get(
        "/v1/favorites", params=params, headers={"X-Anonymous-Id": anon}
    )


def test_save_returns_original_text(client, corpus):
    r = _save(client, 1, note="论用神这一节可作「格局」篇的引子")
    assert r.status_code == 200, r.text
    item = r.json()
    assert item["chunk_id"] == 1
    assert item["title"] == "《子平真诠·卷一·论用神》"
    # 原文来自语料，不是请求里带的字段
    assert item["text"] == CHUNK_A["chunk_text"]
    assert item["sourcefile"] == CHUNK_A["meta"]["sourcefile"]
    assert (item["line_start"], item["line_end"]) == (10, 12)
    assert item["note"] == "论用神这一节可作「格局」篇的引子"
    assert item["created_at"]

    listed = _list(client)
    assert listed.status_code == 200
    assert [x["chunk_id"] for x in listed.json()] == [1]


def test_repeat_save_updates_note_without_duplicating(client, corpus):
    first = _save(client, 1, note="初稿").json()
    second = _save(client, 1, note="改过的批注").json()
    assert second["id"] == first["id"]
    assert second["note"] == "改过的批注"
    assert len(_list(client).json()) == 1


def test_blank_note_stored_as_null(client, corpus):
    item = _save(client, 1, note="   ").json()
    assert item["note"] is None


def test_note_too_long_rejected(client, corpus):
    r = _save(client, 1, note="字" * (materials.MAX_NOTE_CHARS + 1))
    assert r.status_code == 422


def test_unknown_chunk_rejected(client, corpus):
    r = _save(client, 99)
    assert r.status_code == 404
    assert "语料" in r.json()["detail"]
    assert _list(client).json() == []


def test_delete_is_idempotent_failure_and_scoped_to_owner(client, corpus):
    item = _save(client, 1, note="我的", anon="anon-a").json()

    # 别人删不掉，也看不到
    assert _list(client, anon="anon-b").json() == []
    assert _save(client, 1, note="他的", anon="anon-b").status_code == 200
    other = _list(client, anon="anon-b").json()[0]
    assert other["id"] != item["id"]

    r = client.delete(
        f"/v1/favorites/{item['id']}", headers={"X-Anonymous-Id": "anon-b"}
    )
    assert r.status_code == 404
    assert len(_list(client, anon="anon-a").json()) == 1

    r = client.delete(
        f"/v1/favorites/{item['id']}", headers={"X-Anonymous-Id": "anon-a"}
    )
    assert r.status_code == 204
    assert _list(client, anon="anon-a").json() == []

    again = client.delete(
        f"/v1/favorites/{item['id']}", headers={"X-Anonymous-Id": "anon-a"}
    )
    assert again.status_code == 404


def test_list_filter_by_chunk_id(client, corpus):
    _save(client, 1)
    _save(client, 2)
    r = _list(client, chunk_id=2)
    assert r.status_code == 200
    assert [x["chunk_id"] for x in r.json()] == [2]
    assert len(_list(client).json()) == 2


def test_export_markdown_keeps_quote_and_note_apart(client, corpus):
    _save(client, 1, note="第一段批注\n第二行也属于批注")
    _save(client, 2, note="")

    r = client.get("/v1/favorites/export.md", headers={"X-Anonymous-Id": "anon-1"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    disposition = r.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert "filename*=UTF-8''" in disposition

    body = r.text
    assert body.startswith("# 问古 · 古籍素材\n")
    assert "共 2 条" in body

    # 后收藏的在前
    assert body.index("滴天髓") < body.index("子平真诠")

    # 原文逐行引用，笔记单独一行、续行缩进
    assert "> 用神既得，格局自定。\n> 喜忌既定，岁运可知。" in body
    assert "- 笔记：第一段批注\n  第二行也属于批注" in body
    assert "- 原文位置：01_子平/标点组/子平真诠.txt，第 10–12 行" in body
    # 没有笔记的条目不出「笔记：」空行
    assert body.count("- 笔记：") == 1


def test_export_without_favorites_is_still_markdown(client, corpus):
    r = client.get("/v1/favorites/export.md", headers={"X-Anonymous-Id": "anon-none"})
    assert r.status_code == 200
    assert r.text.startswith("# 问古 · 古籍素材\n")
    assert "共 0 条" in r.text


def test_stale_chunk_is_skipped_not_shown_as_other_book(client, corpus):
    _save(client, 1)
    _save(client, 2)
    del corpus[2]  # 语料重编号后，这个 chunk_id 不存在了

    listed = _list(client).json()
    assert [x["chunk_id"] for x in listed] == [1]

    body = client.get(
        "/v1/favorites/export.md", headers={"X-Anonymous-Id": "anon-1"}
    ).text
    assert "共 1 条" in body
    assert "滴天髓" not in body


def test_export_filename_is_date_stamped():
    from datetime import datetime, timezone, timedelta

    now = datetime(2026, 11, 18, 23, 30, tzinfo=timezone(timedelta(hours=8)))
    assert materials.export_filename(now) == "问古素材-20261118.md"
    # UTC 同一天的凌晨在 UTC+8 已经是第二天，文件名按北京时间
    utc = datetime(2026, 11, 18, 20, 0, tzinfo=timezone.utc)
    assert materials.export_filename(utc) == "问古素材-20261119.md"
