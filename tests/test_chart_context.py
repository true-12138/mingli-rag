# -*- coding: utf-8 -*-
"""排盘结果带入对话的边界。

这里守的三条：
1. 盘面只是上下文，引用仍然只能来自检索到的片段；
2. 残缺 / 超大的盘面一律作废，退化成普通问答，不能半截进 prompt；
3. 有盘面时不走语义缓存——缓存 key 里没有盘面，命中就是把别人的盘答给这个人。

测试不加载语料和 embedding：检索、模型调用、多 Agent 各角色都被替换掉。
"""
import sys
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import api  # noqa: E402
import chart_context  # noqa: E402
import gate  # noqa: E402
import rag  # noqa: E402
import semcache  # noqa: E402


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
]


# ---------- 校验与 prompt 组装 ----------

def test_normalize_rejects_garbage():
    assert chart_context.normalize(None) is None
    assert chart_context.normalize("八字") is None
    assert chart_context.normalize({}) is None
    # 类型不认识：宁可退化成普通问答，也不猜字段
    assert chart_context.normalize({"kind": "ziwei", "sizhu": {}}) is None


def test_normalize_rejects_incomplete_chart():
    """缺字段的盘要在入口就淘汰，不能等到拼 prompt 时才 KeyError。"""
    broken = {"kind": "bazi", "day_master": "甲木"}  # 没有 sizhu / 十神 / 大运
    assert chart_context.normalize(broken) is None
    assert chart_context.prompt_block(broken) == ""
    assert chart_context.system_prompt("BASE", broken) == "BASE"


def test_normalize_rejects_oversize_chart():
    big = dict(CHART)
    big["sizhu"] = {key: "甲子" * 4000 for key in CHART["sizhu"]}
    assert chart_context.normalize(big) is None


def test_normalize_accepts_real_chart():
    assert chart_context.normalize(CHART) is CHART


def test_prompt_block_is_fact_not_evidence():
    block = chart_context.prompt_block(CHART)
    assert block.startswith("【盘面】")
    assert "甲木" in block
    assert "不是引用依据" in block


def test_retrieval_query_adds_chart_keywords():
    query = chart_context.retrieval_query(CHART, "我这盘适合什么方向")
    assert "我这盘适合什么方向" in query
    assert "日主 甲木" in query
    # 没有盘面时不能改动用户的问句
    assert chart_context.retrieval_query(None, "什么是羊刃") == "什么是羊刃"


def test_system_prompt_keeps_base_rules():
    base = "原有规则"
    with_chart = chart_context.system_prompt(base, CHART)
    assert with_chart.startswith(base)
    assert chart_context.CHART_RULE in with_chart
    assert chart_context.system_prompt(base, None) == base


# ---------- 相术：特征卡是用户自述，不是识图结论 ----------

CARD = {
    "kind": "physiognomy",
    "subject": "面相",
    "features": {"脸型": "方脸", "眉形": "剑眉", "口形": "阔口"},
    "note": "右眉尾有一道疤",
}


def test_physiognomy_card_roundtrip():
    assert chart_context.normalize(CARD) is CARD
    block = chart_context.prompt_block(CARD)
    assert block.startswith("【盘面】")
    assert "用户自述" in block
    assert "不是图像识别结果" in block
    assert "方脸" in block
    # 不能照搬「程序按历法算出」的说法
    assert "历法" not in block


def test_physiognomy_card_must_be_non_empty():
    assert chart_context.normalize({"kind": "physiognomy", "subject": "面相", "features": {}}) is None
    assert chart_context.normalize({"kind": "physiognomy", "subject": "手相"}) is None
    assert chart_context.normalize({"kind": "physiognomy", "subject": "八字", "features": {"脸型": "方脸"}}) is None


def test_physiognomy_system_prompt_uses_its_own_rule():
    prompt = chart_context.system_prompt("原有规则", CARD)
    assert chart_context.PHYSIOGNOMY_RULE in prompt
    assert chart_context.CHART_RULE not in prompt


def test_physiognomy_retrieval_query_carries_features():
    query = chart_context.retrieval_query(CARD, "我适合做什么")
    assert "我适合做什么" in query
    for word in ("面相", "方脸", "剑眉", "阔口"):
        assert word in query


# ---------- RAG：盘面进 prompt，引用仍来自片段 ----------

def _fake_retrieve(hits):
    return lambda question, top_k=5, mode="rrf": [dict(hit) for hit in hits]


def test_rag_answer_puts_chart_in_prompt_and_keeps_citations(monkeypatch):
    seen = {}

    def fake_chat(messages, temperature=0.0, api_key=None, **kwargs):
        seen["messages"] = messages
        return '{"can_answer": true, "answer": "甲木日主，见羊刃 [1]", "citations": [1]}'

    monkeypatch.setattr(rag, "retrieve_one", _fake_retrieve(HITS))
    monkeypatch.setattr(rag, "_chat", fake_chat)
    # 没有历史时不调模型改写问句，这里显式钉住这个前提
    monkeypatch.setattr(rag, "rewrite_question", lambda q, h, **kw: q)

    out = rag.answer("我这盘适合什么方向", api_key="k", chart=CHART)

    system = seen["messages"][0]["content"]
    user = seen["messages"][1]["content"]
    assert "【盘面】" in user
    assert "日主" in user
    assert chart_context.CHART_RULE in system
    # 引用契约没有因为盘面改变：编号仍指向本轮召回片段
    assert out["citations_chunk_ids"] == [101]
    assert out["citation_map"] == [{"marker": 1, "chunk_id": 101}]
    assert out["invalid_output"] is False


def test_name_chart_allows_answer_without_citations(monkeypatch):
    """五格剖象不是古籍：只按盘面答、不引原文，也不能标成不合规输出。"""
    from fortune.name import build

    seen = {}

    def fake_chat(messages, temperature=0.0, api_key=None, **kwargs):
        seen["messages"] = messages
        return '{"can_answer": true, "answer": "人格15土，这套体系列为大吉。", "citations": []}'

    def no_retrieve(*args, **kwargs):
        raise AssertionError("姓名盘不该检索古籍")

    monkeypatch.setattr(rag, "retrieve_one", no_retrieve)
    monkeypatch.setattr(rag, "_chat", fake_chat)
    monkeypatch.setattr(rag, "rewrite_question", lambda q, h, **kw: q)

    out = rag.answer("人格 15 怎么讲", api_key="k", chart=build("李", "明"))

    system = seen["messages"][0]["content"]
    assert chart_context.NAME_RULE in system
    # 不能因为古籍里没有五格剖象就拒答
    assert "不得以「语料没有依据」拒答" in system
    assert out["invalid_output"] is False
    assert out["citations_chunk_ids"] == []


def test_bazi_chart_still_requires_citations(monkeypatch):
    """同样的「能答但不引用」，八字盘仍按不合规处理，别把规则一起放宽。"""

    def fake_chat(messages, temperature=0.0, api_key=None, **kwargs):
        return '{"can_answer": true, "answer": "甲木日主。", "citations": []}'

    monkeypatch.setattr(rag, "retrieve_one", _fake_retrieve(HITS))
    monkeypatch.setattr(rag, "_chat", fake_chat)
    monkeypatch.setattr(rag, "rewrite_question", lambda q, h, **kw: q)

    out = rag.answer("我这盘适合什么方向", api_key="k", chart=CHART)

    assert out["invalid_output"] is True


def test_rag_answer_without_chart_is_unchanged(monkeypatch):
    seen = {}

    def fake_chat(messages, temperature=0.0, api_key=None, **kwargs):
        seen["messages"] = messages
        return '{"can_answer": true, "answer": "甲木 [1]", "citations": [1]}'

    monkeypatch.setattr(rag, "retrieve_one", _fake_retrieve(HITS))
    monkeypatch.setattr(rag, "_chat", fake_chat)
    monkeypatch.setattr(rag, "rewrite_question", lambda q, h, **kw: q)

    rag.answer("甲木是什么意思", api_key="k")
    assert "【盘面】" not in seen["messages"][1]["content"]
    assert seen["messages"][0]["content"] == rag.SYSTEM_PROMPT


# ---------- 多 Agent：盘面同样进各角色上下文 ----------

def test_multi_agent_threads_chart_into_role_context(monkeypatch):
    import agent_multi

    captured = {}

    def fake_plan(question, counter, feedback="", api_key=None, history=""):
        captured["plan_history"] = history
        return {"pre": [], "searches": [], "out_of_scope": False}

    def fake_verify(question, evidence, pre_notes, out_of_scope, counter,
                    api_key=None, history=""):
        captured["verify_history"] = history
        return {"sufficient": False, "gaps": [], "reason": "无证据"}

    def fake_synthesize(question, evidence, pre_notes, verdict, out_of_scope,
                        counter, api_key=None, history=""):
        captured["synth_history"] = history
        return {"can_answer": False, "answer": "", "citations": []}

    monkeypatch.setattr(agent_multi, "rewrite_question", lambda q, h, **kw: q)
    monkeypatch.setattr(agent_multi, "_plan", fake_plan)
    monkeypatch.setattr(agent_multi, "_verify", fake_verify)
    monkeypatch.setattr(agent_multi, "_synthesize", fake_synthesize)

    out = agent_multi.agent_answer("我这盘怎么样", api_key="k", chart=CHART)

    for key in ("plan_history", "verify_history", "synth_history"):
        assert "【盘面】" in captured[key], key
        assert "甲木" in captured[key], key
    # 汇总员拒答时仍然是标准拒答，不会因为盘面就说「能答」
    assert out["can_answer"] is False


# ---------- API：盘面透传 + 语义缓存必须关掉 ----------

class _FakeEncoder:
    def encode(self, text, normalize_embeddings=True):
        vec = np.zeros(16, dtype=np.float32)
        for ch in str(text):
            vec[ord(ch) % 16] += 1.0
        norm = float(np.linalg.norm(vec)) or 1.0
        return vec / norm


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.delenv("MINGLI_API_TOKEN", raising=False)
    monkeypatch.delenv("MINGLI_REDIS_URL", raising=False)
    gate.reset_for_tests()
    semcache.reset_for_tests()
    semcache.set_encoder(_FakeEncoder())
    yield TestClient(api.app)
    semcache.reset_for_tests()


def _rag_result():
    return {
        "can_answer": True,
        "answer": "测试回答 [1]",
        "citations": [1],
        "citations_chunk_ids": [1],
        "invalid_citations": [],
        "invalid_output": False,
        "refusal_reason": None,
        "retrieved_chunk_ids": [1],
        "rewritten_question": "独立问题",
        "history_turns": 0,
        "llm_calls": 1,
    }


def test_chat_passes_chart_through(client, monkeypatch):
    seen = {}

    def fake_answer(question, top_k=5, mode="rrf", api_key=None, history=None, chart=None, tier="auto"):
        seen["chart"] = chart
        return _rag_result()

    monkeypatch.setattr(api.rag, "answer", fake_answer)
    r = client.post("/chat", json={"question": "我这盘怎么样", "chart": CHART})
    assert r.status_code == 200
    assert seen["chart"]["day_master"] == "甲木"


def test_cache_disabled_when_chart_attached(client, monkeypatch):
    """同一句问题配不同的盘，答案必须不同——缓存 key 里没有盘，所以不能缓存。"""
    calls = []

    def fake_answer(question, top_k=5, mode="rrf", api_key=None, history=None, chart=None, tier="auto"):
        calls.append(chart["day_master"] if chart else None)
        out = _rag_result()
        out["answer"] = "日主 {}".format(chart["day_master"]) if chart else "无盘"
        return out

    monkeypatch.setattr(api.rag, "answer", fake_answer)
    body = {"question": "我这盘怎么样", "chart": CHART}
    assert client.post("/chat", json=body).json()["answer"] == "日主 甲木"
    assert client.post("/chat", json=body).json()["answer"] == "日主 甲木"
    # 两次都真的进了模型，没有第二次直接吃缓存
    assert calls == ["甲木", "甲木"]


def test_cache_still_works_without_chart(client, monkeypatch):
    calls = []

    def fake_answer(question, top_k=5, mode="rrf", api_key=None, history=None, chart=None, tier="auto"):
        calls.append(question)
        return _rag_result()

    monkeypatch.setattr(api.rag, "answer", fake_answer)
    body = {"question": "羊刃分几种"}
    client.post("/chat", json=body)
    client.post("/chat", json=body)
    assert calls == ["羊刃分几种"]
