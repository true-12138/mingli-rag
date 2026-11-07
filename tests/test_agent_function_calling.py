# -*- coding: utf-8 -*-
"""单 Agent 的 function calling 路径（不联网、不加载语料）。

把 tools / rag / conversation 换成 stub，加载真正的 agent.py + tool_loop.py，
验证 tool_calls 能被执行、引用白名单仍然生效、排盘类工具允许无 chunk 引用。
"""
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
REFUSAL = "语料中没有足够的依据回答这个问题。"


class FakeAPI:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, messages, tools=None, temperature=0.0, api_key=None, tool_choice=None):
        self.calls.append({"messages": [dict(m) for m in messages], "tools": tools})
        return self.replies.pop(0)


def _tool_call(cid, name, args):
    return {"id": cid, "type": "function",
            "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}


@pytest.fixture
def env():
    names = ("tools", "rag", "conversation", "agent", "tool_loop")
    saved = {n: sys.modules.get(n) for n in names}

    stub_tools = types.SimpleNamespace(call=None)
    stub_rag = types.SimpleNamespace(
        REFUSAL_TEXT=REFUSAL,
        _chat=lambda *a, **k: "",
        _parse_json=json.loads,
        _chat_message=None,
    )
    stub_conv = types.SimpleNamespace(
        history_block=lambda h: "",
        memory_block=lambda m: "",
        normalize_history=lambda h: h or [],
        rewrite_question=lambda q, h, api_key=None, counter=None: q,
    )
    sys.modules["tools"] = stub_tools
    sys.modules["rag"] = stub_rag
    sys.modules["conversation"] = stub_conv
    sys.modules.pop("agent", None)
    sys.modules.pop("tool_loop", None)

    spec = importlib.util.spec_from_file_location("agent_under_test", SRC / "agent.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    try:
        yield mod, stub_rag, stub_tools
    finally:
        for name, old in saved.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old


def test_tool_call_then_final_json(env):
    mod, stub_rag, stub_tools = env
    stub_rag._chat_message = FakeAPI([
        {"content": None, "tool_calls": [_tool_call("c1", "search_classics", {"query": "正官"})]},
        {"content": json.dumps({"can_answer": True, "answer": "正官为……",
                                "citations": [42], "refusal_reason": None},
                               ensure_ascii=False)},
    ])
    stub_tools.call = lambda name, **kw: {
        "ok": True, "tool": name, "args": kw,
        "result": {"hits": [{"chunk_id": 42, "book": "子平真诠评注",
                             "chapter": "论正官", "text": "原文"}]},
    }

    res = mod.agent_answer("正官是什么意思？", api_key="sk-test")

    assert res["can_answer"] is True
    assert res["citations_chunk_ids"] == [42]
    assert res["steps"] == 1
    assert res["trace"][0]["action"] == "search_classics"
    assert res["tool_mode"] == "function"
    assert res["llm_calls"] == 2


def test_unseen_citation_is_rejected(env):
    mod, stub_rag, stub_tools = env
    stub_rag._chat_message = FakeAPI([
        {"content": None, "tool_calls": [_tool_call("c1", "list_books", {})]},
        {"content": json.dumps({"can_answer": True, "answer": "编的",
                                "citations": [99]})},
    ])
    stub_tools.call = lambda name, **kw: {"ok": True, "result": {"books": []}}

    res = mod.agent_answer("问", api_key="sk-test")

    assert res["can_answer"] is False
    assert res["citations_chunk_ids"] == []
    assert res["invalid_citations"] == [99]
    assert res["invalid_output"] is True


def test_chart_tool_answer_needs_no_chunk_citation(env):
    mod, stub_rag, stub_tools = env
    stub_rag._chat_message = FakeAPI([
        {"content": None, "tool_calls": [_tool_call(
            "c1", "draw_bazi", {"year": 1998, "month": 6, "day": 12})]},
        {"content": json.dumps({"can_answer": True,
                                "answer": "四柱为戊寅、戊午、庚子、丙子。",
                                "citations": []})},
    ])
    stub_tools.call = lambda name, **kw: {"ok": True, "tool": name,
                                          "result": {"pillars": ["戊寅"]}}

    res = mod.agent_answer("帮我排个盘", api_key="sk-test")

    assert res["can_answer"] is True
    assert res["citations_chunk_ids"] == []
    assert res["invalid_output"] is False


def test_two_unparseable_finals_are_reported(env):
    mod, stub_rag, stub_tools = env
    api = FakeAPI([{"content": "不是 JSON"}, {"content": "仍然不是 JSON"}])
    stub_rag._chat_message = api

    res = mod.agent_answer("问", api_key="sk-test")

    assert res["can_answer"] is None
    assert res["invalid_output"] is True
    assert res["error"] == "JSON 解析失败"
    assert len(api.calls) == 2
    assert "不要再调用工具" in api.calls[1]["messages"][-1]["content"]
