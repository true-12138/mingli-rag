# -*- coding: utf-8 -*-
"""盘面解读接入 RAG 的测试。

这三件事必须成立：
1. 解读 prompt 里真的有检索到的古籍片段，而不是只有盘面；
2. 模型引用的 [n] 能映射回 chunk_id，越界编号被丢掉；
3. 检索失败时退化为纯盘面解读，不能把整个解读拖垮。

测试不加载语料和 embedding：检索函数和 rag 的 chat 都被替换掉。
"""
import json
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fortune import interpret


CHART = {
    "kind": "bazi",
    "sizhu": {"年柱": "乙亥", "月柱": "甲申", "日柱": "甲子", "时柱": "辛未"},
    "rizhu": "甲子",
    "day_master": "甲木",
    "shengxiao": "猪",
    "canggan": {"年柱": ["壬", "甲"], "月柱": ["庚", "壬", "戊"]},
    "shishen_gan": {"年柱": "劫财", "月柱": "比肩", "日柱": "日主", "时柱": "正官"},
    "shishen_zhi": {"年柱": ["偏印"], "月柱": ["七杀"], "日柱": ["正印"], "时柱": ["正财"]},
    "nayin": {"年柱": "山头火", "月柱": "泉中水", "日柱": "海中金", "时柱": "路旁土"},
    "wuxing": {"木": 3, "火": 0, "土": 2, "金": 2, "水": 1},
    "wuxing_missing": ["火"],
    "qiyun": {"years": 3, "months": 2, "days": 1, "forward": True},
    "dayun": [{"start_year": 1998, "start_age": 4, "ganzhi": "乙酉"}],
    "current_dayun": {"start_year": 2018, "start_age": 24, "ganzhi": "丁亥"},
}

HITS = [
    {
        "chunk_id": 101,
        "chunk_idx": 0,
        "rrf_score": 0.03,
        "text": "甲木参天，脱胎要火。",
        "meta": {"book": "滴天髓", "volume": "上", "chapter": "天干"},
    },
    {
        "chunk_id": 102,
        "chunk_idx": 1,
        "rrf_score": 0.02,
        "text": "正官者，乃甲见辛之类。",
        "meta": {"book": "三命通会", "volume": "", "chapter": "论十神"},
    },
]


def _fake_rag(reply, seen):
    """冒充 rag 模块：只提供 build_context / _chat / _parse_json。"""
    module = types.ModuleType("rag")

    def build_context(hits):
        lines = []
        for i, hit in enumerate(hits, 1):
            meta = hit["meta"]
            title = "《{}》".format(
                "·".join(
                    part for part in (meta.get("book"), meta.get("volume"),
                                      meta.get("chapter")) if part
                )
            )
            lines.append("[{}] {}\n{}".format(i, title, hit["text"]))
        return "\n\n".join(lines)

    def _chat(messages, temperature=0.0, api_key=None):
        seen["messages"] = messages
        return reply if isinstance(reply, str) else json.dumps(
            reply, ensure_ascii=False
        )

    def _parse_json(raw):
        return json.loads(raw)

    module.build_context = build_context
    module._chat = _chat
    module._parse_json = _parse_json
    return module


def test_read_retrieves_fragments_and_maps_citations(monkeypatch):
    seen = {}

    def fake_retrieve(chart, question=None, top_k=5):
        seen["query"] = interpret._retrieval_query(chart, question)
        assert top_k == 5
        return HITS, seen["query"]

    reply = {
        "summary": "甲木日主，见火则发。",
        "sections": [{"title": "日主", "content": "甲木参天 [1]，正官为辛 [1][2]。"}],
        "citations": [1, 2, 9, 1],
        "disclaimer": "仅供文化参考",
    }
    monkeypatch.setattr(interpret, "_retrieve_fragments", fake_retrieve)
    monkeypatch.setitem(sys.modules, "rag", _fake_rag(reply, seen))

    result = interpret.read(CHART, question="适合做什么方向？")

    assert result["citations_chunk_ids"] == [101, 102]
    assert result["citation_map"] == [
        {"marker": 1, "chunk_id": 101},
        {"marker": 2, "chunk_id": 102},
    ]
    # 越界编号被丢掉；重复引用只留一条出处
    assert result["invalid_citations"] == [9]
    assert result["retrieved_chunk_ids"] == [101, 102]

    user = seen["messages"][1]["content"]
    assert "【古籍片段】" in user
    assert "《滴天髓" in user
    assert "甲木参天，脱胎要火。" in user
    assert "【用户的问题】\n适合做什么方向？" in user


def test_read_survives_retrieval_failure(monkeypatch):
    seen = {}

    def boom(chart, question=None, top_k=5):
        raise RuntimeError("embeddings.npy 不存在")

    reply = {
        "summary": "只按盘面说。",
        "sections": [{"title": "结构", "content": "甲木日主 [1]。"}],
        "citations": [1],
        "disclaimer": "仅供文化参考",
    }
    monkeypatch.setattr(interpret, "_retrieve_fragments", boom)
    monkeypatch.setitem(sys.modules, "rag", _fake_rag(reply, seen))

    result = interpret.read(CHART)

    # 解读照常返回；没有片段，引用一律作废
    assert result["sections"][0]["content"] == "甲木日主 [1]。"
    assert result["citations_chunk_ids"] == []
    assert result["citation_map"] == []
    assert result["invalid_citations"] == [1]
    assert result["retrieved_chunk_ids"] == []
    assert "没有检索到可用片段" in seen["messages"][1]["content"]


def test_retrieval_query_uses_chart_terms_and_question():
    query = interpret._retrieval_query(CHART, "事业发展")
    assert "甲木" in query
    assert "十神" in query
    assert "正官" in query
    assert "缺 火" in query
    assert query.endswith("事业发展")

    # 三种盘都要能生成问句，不能因为缺字段就抛异常
    assert interpret._retrieval_query({"kind": "astro"}) == ""
    assert interpret._retrieval_query(
        {"kind": "astro", "asc": {"sign": "巨蟹"}, "planets": [], "aspects": []}
    ) == "上升 巨蟹"
    assert "愚者" in interpret._retrieval_query(
        {"kind": "tarot", "spread": "single",
         "cards": [{"name": "愚者"}]}
    )


def test_parse_error_keeps_retrieved_chunk_ids(monkeypatch):
    seen = {}

    def fake_retrieve(chart, question=None, top_k=5):
        return HITS, "日主 甲木"

    monkeypatch.setattr(interpret, "_retrieve_fragments", fake_retrieve)
    monkeypatch.setitem(sys.modules, "rag", _fake_rag("这不是 JSON", seen))

    result = interpret.read(CHART)

    assert result["parse_error"] is True
    assert result["retrieved_chunk_ids"] == [101, 102]
    assert result["citations_chunk_ids"] == []
