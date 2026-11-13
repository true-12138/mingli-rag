# -*- coding: utf-8 -*-
"""function calling 协议层测试：不联网、不加载语料。

用 stub 替换 sys.modules 里的 rag / tools，再加载真正的 tool_loop.py，
只验证「tool_calls → 执行 → role=tool 回灌 → 收口」这条链路。
"""
import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"


def _tool_call(cid, name, args):
    return {
        "id": cid,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
    }


class FakeAPI:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, messages, tools=None, temperature=0.0, api_key=None, tool_choice=None):
        self.calls.append({
            "messages": [dict(m) for m in messages],
            "tools": tools,
            "tool_choice": tool_choice,
        })
        return self.replies.pop(0)


@pytest.fixture
def mods():
    names = ("rag", "tools", "tool_loop")
    saved = {n: sys.modules.get(n) for n in names}
    fake_rag = types.SimpleNamespace(_chat_message=None)
    fake_tools = types.SimpleNamespace(call=None)
    sys.modules["rag"] = fake_rag
    sys.modules["tools"] = fake_tools
    sys.modules.pop("tool_loop", None)

    spec = importlib.util.spec_from_file_location("tool_loop_under_test", SRC / "tool_loop.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        yield mod, fake_rag, fake_tools
    finally:
        for name, old in saved.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old


def test_tool_call_is_executed_and_returned_to_model(mods):
    mod, fake_rag, fake_tools = mods
    api = FakeAPI([
        {"content": None, "tool_calls": [_tool_call("c1", "search_classics", {"query": "正官"})]},
        {"content": '{"thought": "够了"}'},
    ])
    fake_rag._chat_message = api
    seen_calls = []

    def fake_call(name, **kwargs):
        seen_calls.append((name, kwargs))
        return {"ok": True, "tool": name, "args": kwargs,
                "result": {"hits": [{"chunk_id": 11}]}}

    fake_tools.call = fake_call
    trace = []
    messages = [{"role": "user", "content": "问"}]

    content, messages, used = mod.run(
        messages, max_calls=3, schemas=[{"type": "function"}],
        prepare=lambda name, args: dict(args, book="子平真诠"),
        on_call=lambda name, args, result: trace.append((name, args, result["ok"])),
        counter={"llm_calls": 0},
    )

    assert content == '{"thought": "够了"}'
    assert used == 1
    assert seen_calls == [("search_classics", {"query": "正官", "book": "子平真诠"})]
    assert trace == [("search_classics", {"query": "正官", "book": "子平真诠"}, True)]

    assistant, tool_msg = messages[-2], messages[-1]
    assert assistant["role"] == "assistant"
    assert assistant["tool_calls"][0]["id"] == "c1"
    assert tool_msg["role"] == "tool"
    assert tool_msg["tool_call_id"] == "c1"
    assert json.loads(tool_msg["content"])["result"]["hits"][0]["chunk_id"] == 11

    # 第二轮请求带着 tool 消息，且仍然开放工具
    second = api.calls[1]["messages"]
    assert second[-1]["role"] == "tool"
    assert api.calls[1]["tools"] is not None


def test_budget_caps_multi_calls_and_forces_final_without_tools(mods):
    mod, fake_rag, fake_tools = mods
    api = FakeAPI([
        {"content": "", "tool_calls": [
            _tool_call("c1", "search_classics", {"query": "甲"}),
            _tool_call("c2", "search_classics", {"query": "乙"}),
        ]},
        {"content": '{"thought": "ok"}'},
    ])
    fake_rag._chat_message = api
    executed = []
    fake_tools.call = lambda name, **kw: (
        executed.append(kw["query"]) or {"ok": True, "result": {"hits": []}})

    content, messages, used = mod.run(
        [{"role": "user", "content": "问"}], max_calls=1,
        schemas=[{"type": "function"}],
    )

    assert executed == ["甲"]
    assert used == 1
    budget_msg = json.loads(messages[-1]["content"])
    assert budget_msg["ok"] is False and "预算" in budget_msg["error"]
    # 预算用完后，下一轮必须不再传 tools，模型只能直接收口
    assert api.calls[1]["tools"] is None
    assert content == '{"thought": "ok"}'


class FakeStreamAPI:
    """异步版的 FakeAPI：每轮一组事件，和 llm.stream() 的事件协议一致。"""

    def __init__(self, rounds):
        self.rounds = list(rounds)
        self.calls = []

    async def stream(self, messages, **kwargs):
        self.calls.append({
            "messages": [dict(m) for m in messages],
            "tools": kwargs.get("tools"),
            "tool_choice": kwargs.get("tool_choice"),
            "response_format": kwargs.get("response_format"),
        })
        for event in self.rounds.pop(0):
            yield event


def _delta(text):
    return {"type": "delta", "text": text}


def _message(content=None, tool_calls=None, usage=None):
    msg = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return {"type": "message", "message": msg, "usage": usage or {"total_tokens": 3}}


def test_arun_streams_answer_and_executes_tools(mods):
    mod, _fake_rag, fake_tools = mods
    api = FakeStreamAPI([
        [_message(tool_calls=[_tool_call("c1", "search_classics", {"query": "正官"})])],
        [_delta('{"can_answer": true, "ans'), _delta('wer": "正官为官星'),
         _delta('之首"}'),
         _message('{"can_answer": true, "answer": "正官为官星之首"}')],
    ])
    fake_tools.call = lambda name, **kw: {"ok": True, "result": {"hits": [{"chunk_id": 7}]}}
    deltas = []

    content, messages, used = asyncio.run(mod.arun(
        [{"role": "user", "content": "问"}],
        max_calls=2,
        schemas=[{"type": "function"}],
        on_delta=deltas.append,
        client=api,
    ))

    assert "".join(deltas) == "正官为官星之首"
    assert used == 1
    assert json.loads(content)["answer"] == "正官为官星之首"
    assert messages[-2]["role"] == "assistant"
    assert messages[-1]["role"] == "tool"
    # 第一轮带 tools，第二轮仍然开放工具
    assert api.calls[0]["tools"] is not None
    assert api.calls[1]["tools"] is not None


def test_arun_budget_forces_final_without_tools(mods):
    mod, _fake_rag, fake_tools = mods
    api = FakeStreamAPI([
        [_message(tool_calls=[
            _tool_call("c1", "search_classics", {"query": "甲"}),
            _tool_call("c2", "search_classics", {"query": "乙"}),
        ])],
        [_delta('{"thought": "ok"}'), _message('{"thought": "ok"}')],
    ])
    executed = []
    fake_tools.call = lambda name, **kw: (
        executed.append(kw["query"]) or {"ok": True, "result": {"hits": []}})

    _content, messages, used = asyncio.run(mod.arun(
        [{"role": "user", "content": "问"}], max_calls=1,
        schemas=[{"type": "function"}], client=api,
    ))

    assert executed == ["甲"]
    assert used == 1
    assert json.loads(messages[-1]["content"])["error"].startswith("步数预算已用完")
    assert api.calls[1]["tools"] is None
    assert api.calls[1]["response_format"] == {"type": "json_object"}


def test_arun_counts_usage(mods):
    mod, _fake_rag, fake_tools = mods
    api = FakeStreamAPI([
        [_message('{"can_answer": false}', usage={"total_tokens": 11})],
    ])
    counter = {"llm_calls": 0}

    asyncio.run(mod.arun(
        [{"role": "user", "content": "问"}], max_calls=1,
        schemas=[{"type": "function"}], counter=counter, client=api,
    ))

    assert counter["llm_calls"] == 1
    assert counter["usage"] == [{"total_tokens": 11}]


def test_invalid_arguments_are_reported_not_raised(mods):
    mod, fake_rag, fake_tools = mods
    api = FakeAPI([
        {"content": "", "tool_calls": [{
            "id": "c1", "type": "function",
            "function": {"name": "search_classics", "arguments": "{not json"},
        }]},
        {"content": '{"thought": "改好了"}'},
    ])
    fake_rag._chat_message = api
    called = []
    fake_tools.call = lambda name, **kw: called.append(name) or {"ok": True}

    content, messages, used = mod.run(
        [{"role": "user", "content": "问"}], max_calls=2,
        schemas=[{"type": "function"}],
    )

    assert called == []
    assert used == 1
    err = json.loads(messages[-1]["content"])
    assert err["ok"] is False and "JSON" in err["error"]
    assert content == '{"thought": "改好了"}'


# --------------------------------------------------------------------------- #
# 权限分级
# --------------------------------------------------------------------------- #
def _denying_permission(name):
    return {"allowed": False, "tier": "side_effect",
            "reason": "工具 %s 属于 side_effect，需要用户确认后执行" % name}


def test_side_effect_tool_is_denied_and_not_executed(mods):
    mod, fake_rag, fake_tools = mods
    api = FakeAPI([
        {"content": "", "tool_calls": [
            _tool_call("c1", "mcp__remote__delete_all", {"book": "全部"}),
        ]},
        {"content": '{"thought": "需要用户确认"}'},
    ])
    fake_rag._chat_message = api
    fake_tools.permission = _denying_permission
    executed = []
    fake_tools.call = lambda name, **kw: executed.append(name) or {"ok": True}
    trace = []

    content, messages, used = mod.run(
        [{"role": "user", "content": "问"}], max_calls=3,
        schemas=[{"type": "function"}],
        on_call=lambda name, args, result: trace.append((name, args, result)),
    )

    assert executed == []                      # 有副作用的工具一次都没执行
    assert used == 1                           # 但这次尝试仍占一步，防止模型反复重试
    denial = json.loads(messages[-1]["content"])
    assert denial["ok"] is False
    assert denial["requires_confirmation"] is True
    assert denial["tier"] == "side_effect"
    assert denial["args"] == {"book": "全部"}  # 参数保留，用户确认后原样执行
    assert trace[0][2]["requires_confirmation"] is True
    assert content == '{"thought": "需要用户确认"}'


def test_side_effect_tool_runs_after_user_confirmation(mods):
    mod, fake_rag, fake_tools = mods
    api = FakeAPI([
        {"content": "", "tool_calls": [
            _tool_call("c1", "mcp__remote__delete_all", {"book": "全部"}),
        ]},
        {"content": '{"thought": "已执行"}'},
    ])
    fake_rag._chat_message = api
    fake_tools.permission = _denying_permission
    executed = []
    fake_tools.call = lambda name, **kw: (
        executed.append((name, kw)) or {"ok": True, "result": {"deleted": 1}})

    content, messages, used = mod.run(
        [{"role": "user", "content": "问"}], max_calls=3,
        schemas=[{"type": "function"}],
        allow_side_effects=True,
    )

    assert executed == [("mcp__remote__delete_all", {"book": "全部"})]
    assert used == 1
    assert json.loads(messages[-1]["content"])["result"] == {"deleted": 1}
    assert content == '{"thought": "已执行"}'


def test_denied_side_effect_is_also_blocked_in_arun(mods):
    mod, _fake_rag, fake_tools = mods
    api = FakeStreamAPI([
        [_message(tool_calls=[
            _tool_call("c1", "mcp__remote__delete_all", {"book": "全部"}),
        ])],
        [_message('{"thought": "等确认"}')],
    ])
    fake_tools.permission = _denying_permission
    executed = []
    fake_tools.call = lambda name, **kw: executed.append(name) or {"ok": True}

    _content, messages, used = asyncio.run(mod.arun(
        [{"role": "user", "content": "问"}], max_calls=2,
        schemas=[{"type": "function"}], client=api,
    ))

    assert executed == []
    assert used == 1
    denial = json.loads(messages[-1]["content"])
    assert denial["requires_confirmation"] is True


# --------------------------------------------------------------------------- #
# token 预算
# --------------------------------------------------------------------------- #
def test_token_budget_forces_final_without_tools(mods):
    mod, fake_rag, fake_tools = mods
    api = FakeAPI([
        {"content": "", "usage": {"total_tokens": 12}, "tool_calls": [
            _tool_call("c1", "search_classics", {"query": "甲"}),
        ]},
        {"content": '{"thought": "省着点"}'},
    ])
    fake_rag._chat_message = api
    executed = []
    fake_tools.call = lambda name, **kw: executed.append(name) or {"ok": True}

    content, messages, used = mod.run(
        [{"role": "user", "content": "问"}], max_calls=5,
        schemas=[{"type": "function"}], max_tokens=10,
    )

    # 第一步就把额度花完了：这次工具调用不再执行（也不计步），下一轮不传 tools
    assert executed == []
    assert used == 0
    assert json.loads(messages[-1]["content"])["error"].startswith("token 预算已用完")
    assert api.calls[1]["tools"] is None
    assert content == '{"thought": "省着点"}'


def test_token_usage_accumulates_across_rounds_and_reruns(mods):
    mod, fake_rag, fake_tools = mods
    api = FakeAPI([
        {"content": "", "usage": {"total_tokens": 7}, "tool_calls": [
            _tool_call("c1", "search_classics", {"query": "甲"}),
        ]},
        {"content": '{"thought": "ok"}', "usage": {"total_tokens": 5}},
    ])
    fake_rag._chat_message = api
    fake_tools.call = lambda name, **kw: {"ok": True, "result": {}}
    counter = {"llm_calls": 0}

    mod.run(
        [{"role": "user", "content": "问"}], max_calls=3,
        schemas=[{"type": "function"}], counter=counter,
    )
    assert counter["tokens_used"] == 12
    assert counter["usage"] == [{"total_tokens": 7}, {"total_tokens": 5}]

    # 同一个 counter 再跑一次（终稿 JSON 失败后的重跑）要接着累计，不能清零
    api.replies = [{"content": '{"thought": "again"}', "usage": {"total_tokens": 3}}]
    mod.run(
        [{"role": "user", "content": "问"}], max_calls=3,
        schemas=[{"type": "function"}], counter=counter,
    )
    assert counter["tokens_used"] == 15


def test_arun_token_budget_and_usage(mods):
    mod, _fake_rag, fake_tools = mods
    api = FakeStreamAPI([
        [_message(tool_calls=[_tool_call("c1", "search_classics", {"query": "甲"})],
                  usage={"total_tokens": 11})],
        [_message('{"thought": "ok"}', usage={"total_tokens": 2})],
    ])
    executed = []
    fake_tools.call = lambda name, **kw: executed.append(name) or {"ok": True}
    counter = {"llm_calls": 0}

    asyncio.run(mod.arun(
        [{"role": "user", "content": "问"}], max_calls=3,
        schemas=[{"type": "function"}], max_tokens=10,
        counter=counter, client=api,
    ))

    assert executed == []
    assert counter["tokens_used"] == 13
    assert api.calls[1]["tools"] is None

