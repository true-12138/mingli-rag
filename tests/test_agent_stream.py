# -*- coding: utf-8 -*-
"""单 Agent 的流式路径：逐 token 下发 + step 事件 + 引用白名单。

不联网、不加载语料：和 test_agent_function_calling.py 一样，
把 tools / rag / conversation 换成 stub，加载真正的 agent.py + tool_loop.py。
"""
import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
REFUSAL = "语料中没有足够的依据回答这个问题。"


def _tool_call(cid, name, args):
    return {"id": cid, "type": "function",
            "function": {"name": name,
                         "arguments": json.dumps(args, ensure_ascii=False)}}


def _delta(text):
    return {"type": "delta", "text": text}


def _message(content=None, tool_calls=None, usage=None):
    msg = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return {"type": "message", "message": msg, "usage": usage}


class FakeClient:
    """llm.LLMClient 的最小替身：按脚本逐轮 yield 事件。"""

    def __init__(self, rounds):
        self.rounds = list(rounds)
        self.calls = []

    async def stream(self, messages, **kwargs):
        self.calls.append({
            "messages": [dict(m) for m in messages],
            "tools": kwargs.get("tools"),
            "response_format": kwargs.get("response_format"),
        })
        for event in self.rounds.pop(0):
            yield event


@pytest.fixture
def env():
    names = ("tools", "rag", "conversation", "agent", "tool_loop", "llm")
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
        arewrite_question=None,
    )

    async def _no_rewrite(question, history, api_key=None, counter=None, client=None):
        return question

    stub_conv.arewrite_question = _no_rewrite

    sys.modules["tools"] = stub_tools
    sys.modules["rag"] = stub_rag
    sys.modules["conversation"] = stub_conv
    sys.modules.pop("agent", None)
    sys.modules.pop("tool_loop", None)

    spec = importlib.util.spec_from_file_location("agent_stream_under_test", SRC / "agent.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    try:
        yield mod, stub_tools
    finally:
        for name, old in saved.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old


def test_stream_emits_answer_tokens_and_steps(env):
    mod, stub_tools = env
    client = FakeClient([
        [_message(tool_calls=[_tool_call("c1", "search_classics", {"query": "正官"})],
                  usage={"total_tokens": 4})],
        [_delta('{"can_answer": true, "ans'), _delta('wer": "正官'),
         _delta('为官星之首"}'),
         _message('{"can_answer": true, "answer": "正官为官星之首", "citations": [42]}',
                  usage={"total_tokens": 6})],
    ])
    stub_tools.call = lambda name, **kw: {
        "ok": True, "tool": name, "args": kw,
        "result": {"hits": [{"chunk_id": 42, "book": "子平真诠评注",
                             "chapter": "论正官", "text": "原文"}]},
    }
    deltas, steps = [], []

    res = asyncio.run(mod.agent_answer_stream(
        "正官是什么意思？", api_key="sk-test", client=client,
        on_delta=deltas.append, on_step=steps.append,
    ))

    assert "".join(deltas) == "正官为官星之首"
    assert res["can_answer"] is True
    assert res["citations_chunk_ids"] == [42]
    assert res["usage"]["total_tokens"] == 10
    assert res["llm_calls"] == 2
    assert steps == [{
        "agent": "agent",
        "tool": "search_classics",
        "args": {"query": "正官"},
        "ok": True,
        "chunk_ids": [42],
        "error": None,
    }]


def test_stream_withholds_tool_round_text(env):
    """工具轮的正文里没有 answer 字段时，一个 delta 都不该下发。"""
    mod, stub_tools = env
    client = FakeClient([
        [_delta("我先检索一下《子平真诠评注》。"),
         _message("我先检索一下《子平真诠评注》。",
                  tool_calls=[_tool_call("c1", "search_classics", {"query": "羊刃"})])],
        [_delta('{"can_answer": false, "answer": "语料中没有足够的依据回答这个问题。"}'),
         _message('{"can_answer": false, "answer": "语料中没有足够的依据回答这个问题。"}')],
    ])
    stub_tools.call = lambda name, **kw: {"ok": True, "result": {"hits": []}}
    deltas = []

    res = asyncio.run(mod.agent_answer_stream(
        "问", api_key="sk-test", client=client, on_delta=deltas.append,
    ))

    assert "".join(deltas) == REFUSAL
    assert res["can_answer"] is False
    assert res["answer"] == REFUSAL
    assert res["citations_chunk_ids"] == []


def test_stream_never_retries_after_emitting_tokens(env):
    """终稿 JSON 解析失败要重试，但已经下发过的正文不能再放一遍。"""
    mod, _stub_tools = env
    client = FakeClient([
        [_delta('{"answer": "半截'), _message('{"answer": "半截')],
        # 第二次尝试：真实的 JSON
        [_delta('{"answer": "完整答案", "can_answer": true, "citations": []}'),
         _message('{"answer": "完整答案", "can_answer": true, "citations": []}')],
    ])
    deltas = []

    res = asyncio.run(mod.agent_answer_stream(
        "问", api_key="sk-test", client=client, on_delta=deltas.append,
    ))

    # 第一次已经下发「半截」，第二次不再重放；终稿以 res 为准
    assert "".join(deltas) == "半截"
    assert res["answer"] == "完整答案"
    assert len(client.calls) == 2
