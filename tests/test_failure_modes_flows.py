# -*- coding: utf-8 -*-
"""失败模式清单：工具调用 / 终稿解析 / 预算 / 上下文裁剪。

这份文件把「实现坏掉时会发生什么」固定成可执行的清单，测的不是正常路径，
而是每一类失败都必须以**可恢复、可复盘、不污染证据**的方式落地：

1. 工具执行抛异常 → 回一条 ok=False 的 observation，循环继续；
2. 异步版同样不能因工具异常而崩；
3. 工具名拼错 → 模型拿到可用工具列表，自己纠正；
4. 一次多个 tool_calls，其中一个参数不是合法 JSON → 坏的报错、好的照跑；
5. 终稿 JSON 解析失败 → 追加纠正 observation 重跑一次；
6. 两次都失败 → invalid_output=True，raw 保留；
7. 步数预算用尽 → 强制拒答，trace 长度等于 max_steps；
8. 历史裁剪有信息损失上限，且显式标注「不作为回答证据」；
9. 记忆块同样有上限，超长值截断处带「…」标记；
10. 被拒绝/失败的调用仍进 trace 供复盘，但不能变成引用证据。

不联网、不加载真实语料：tool_loop 用 sys.modules stub 替换 rag/tools；
agent 额外替换 conversation；fixture 退出时恢复所有被替换的 sys.modules。
"""
import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

import conversation  # noqa: E402
from tool_schema import SCHEMAS  # noqa: E402

REFUSAL = "语料中没有足够的依据回答这个问题。"


# --------------------------------------------------------------------------- #
# 共用 stub
# --------------------------------------------------------------------------- #
def _tool_call(cid, name, args):
    return {
        "id": cid,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
    }


class FakeAPI:
    """同步 _chat_message 的假实现：按顺序返回完整 message。"""

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


# --------------------------------------------------------------------------- #
# fixture：只加载 tool_loop.py，rag/tools 换成 stub
# --------------------------------------------------------------------------- #
@pytest.fixture
def loop_env():
    names = ("rag", "tools", "tool_loop")
    saved = {n: sys.modules.get(n) for n in names}

    fake_rag = types.SimpleNamespace(_chat_message=None)
    fake_tools = types.SimpleNamespace(call=None)
    sys.modules["rag"] = fake_rag
    sys.modules["tools"] = fake_tools
    sys.modules.pop("tool_loop", None)

    spec = importlib.util.spec_from_file_location(
        "tool_loop_failure_under_test", SRC / "tool_loop.py")
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


# --------------------------------------------------------------------------- #
# fixture：加载真正的 agent.py，tools/rag/conversation 换成 stub
# --------------------------------------------------------------------------- #
@pytest.fixture
def agent_env(monkeypatch):
    # agent.py 在 import 时读 TOOL_MODE；固定成 function calling 路径再加载。
    monkeypatch.setenv("MINGLI_TOOL_MODE", "function")
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

    spec = importlib.util.spec_from_file_location(
        "agent_failure_under_test", SRC / "agent.py")
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


# --------------------------------------------------------------------------- #
# 1. 同步：工具执行抛异常
# --------------------------------------------------------------------------- #
def test_tool_exception_is_returned_as_failed_observation(loop_env):
    mod, fake_rag, fake_tools = loop_env
    api = FakeAPI([
        {"content": None,
         "tool_calls": [_tool_call("c1", "search_classics", {"query": "正官"})]},
        {"content": '{"can_answer": false, "answer": ""}'},
    ])
    fake_rag._chat_message = api

    def boom(name, **kwargs):
        raise RuntimeError("index shard offline")

    fake_tools.call = boom
    trace = []

    content, messages, used = mod.run(
        [{"role": "user", "content": "问"}],
        max_calls=3,
        schemas=[{"type": "function"}],
        on_call=lambda name, args, result: trace.append((name, args, result)),
    )

    # 异常被压成 observation，不把循环带走；这次尝试仍计一步
    assert used == 1
    assert messages[-1]["role"] == "tool"
    assert messages[-1]["tool_call_id"] == "c1"
    observation = json.loads(messages[-1]["content"])
    assert observation["ok"] is False
    assert observation["tool"] == "search_classics"
    assert "RuntimeError" in observation["error"]
    assert "index shard offline" in observation["error"]
    # on_call 也收到了失败结果，trace 能复盘
    assert trace[0][0] == "search_classics"
    assert trace[0][2]["ok"] is False
    # 循环继续到终稿，下一轮仍然开放工具
    assert content == '{"can_answer": false, "answer": ""}'
    assert api.calls[1]["tools"] is not None
    assert api.calls[1]["messages"][-1]["role"] == "tool"


# --------------------------------------------------------------------------- #
# 2. 异步：工具执行抛异常
# --------------------------------------------------------------------------- #
def test_async_tool_exception_is_returned_as_failed_observation(loop_env):
    mod, _fake_rag, fake_tools = loop_env
    api = FakeStreamAPI([
        [_message(tool_calls=[
            _tool_call("c1", "search_classics", {"query": "正官"}),
        ])],
        [_delta('{"can_answer": false}'), _message('{"can_answer": false}')],
    ])

    def boom(name, **kwargs):
        raise RuntimeError("bm25 backend crashed")

    fake_tools.call = boom
    trace = []

    content, messages, used = asyncio.run(mod.arun(
        [{"role": "user", "content": "问"}],
        max_calls=3,
        schemas=[{"type": "function"}],
        on_call=lambda name, args, result: trace.append((name, args, result)),
        client=api,
    ))

    assert used == 1
    observation = json.loads(messages[-1]["content"])
    assert messages[-1]["tool_call_id"] == "c1"
    assert observation["ok"] is False
    assert "RuntimeError" in observation["error"]
    assert "bm25 backend crashed" in observation["error"]
    assert trace[0][2]["ok"] is False
    assert json.loads(content)["can_answer"] is False
    assert api.calls[1]["tools"] is not None


# --------------------------------------------------------------------------- #
# 3. 工具名拼错
# --------------------------------------------------------------------------- #
def test_unknown_tool_name_reports_available_tools(loop_env):
    mod, fake_rag, fake_tools = loop_env
    available = sorted(s["function"]["name"] for s in SCHEMAS)
    api = FakeAPI([
        {"content": None,
         "tool_calls": [_tool_call("c1", "search_classic", {"query": "正官"})]},
        {"content": '{"can_answer": false, "answer": ""}'},
    ])
    fake_rag._chat_message = api
    # 复刻 tools.call 的未知工具分支：ok=False + 可用工具列表
    fake_tools.call = lambda name, **kw: {
        "ok": False,
        "tool": name,
        "args": kw,
        "error": "未知工具，可用：%s" % ", ".join(available),
    }

    content, messages, used = mod.run(
        [{"role": "user", "content": "问"}],
        max_calls=3,
        schemas=[{"type": "function"}],
    )

    assert used == 1
    observation = json.loads(messages[-1]["content"])
    assert observation["ok"] is False
    assert observation["tool"] == "search_classic"
    assert observation["error"].startswith("未知工具")
    # 模型在下一轮请求里确实拿到了可用工具列表
    fed_back = api.calls[1]["messages"][-1]
    assert fed_back["role"] == "tool" and fed_back["tool_call_id"] == "c1"
    for name in available:
        assert name in fed_back["content"]
    assert content == '{"can_answer": false, "answer": ""}'


# --------------------------------------------------------------------------- #
# 4. 多个 tool_calls 中一个参数不是合法 JSON
# --------------------------------------------------------------------------- #
def test_one_invalid_json_arguments_does_not_block_sibling_tool_call(loop_env):
    mod, fake_rag, fake_tools = loop_env
    api = FakeAPI([
        {"content": "", "tool_calls": [
            _tool_call("c1", "search_classics", {"query": "正官"}),
            # 手工构造坏 JSON，_tool_call 会帮我们 json.dumps
            {"id": "c2", "type": "function",
             "function": {"name": "fetch_chunk", "arguments": "{chunk_id: 3}"}},
        ]},
        {"content": '{"can_answer": false, "answer": ""}'},
    ])
    fake_rag._chat_message = api
    executed = []
    fake_tools.call = lambda name, **kw: (
        executed.append((name, kw))
        or {"ok": True, "result": {"hits": [{"chunk_id": 7}]}})

    content, messages, used = mod.run(
        [{"role": "user", "content": "问"}],
        max_calls=4,
        schemas=[{"type": "function"}],
    )

    # 好的那个照常执行，坏的那个没有落到 tools.call
    assert executed == [("search_classics", {"query": "正官"})]
    # 坏调用也占一步（每次尝试都要计数，防止模型靠坏参数刷步数）
    assert used == 2

    tool_messages = [m for m in messages if m.get("role") == "tool"]
    assert [m["tool_call_id"] for m in tool_messages] == ["c1", "c2"]
    assert json.loads(tool_messages[0]["content"])["ok"] is True
    bad = json.loads(tool_messages[1]["content"])
    assert bad["ok"] is False
    assert bad["tool"] == "fetch_chunk"
    assert "JSON" in bad["error"]
    assert content == '{"can_answer": false, "answer": ""}'


# --------------------------------------------------------------------------- #
# 5. 终稿 JSON 解析失败后重跑一次（第二次成功）
# --------------------------------------------------------------------------- #
def test_final_json_parse_failure_retries_once_and_recovers(agent_env):
    mod, stub_rag, stub_tools = agent_env
    good_final = json.dumps(
        {"can_answer": True, "answer": "正官为官星之首。", "citations": [42],
         "refusal_reason": None},
        ensure_ascii=False,
    )
    api = FakeAPI([
        {"content": None,
         "tool_calls": [_tool_call("c1", "search_classics", {"query": "正官"})]},
        {"content": "这是一段解释，不是 JSON"},
        {"content": good_final},
    ])
    stub_rag._chat_message = api
    stub_tools.call = lambda name, **kw: {
        "ok": True, "tool": name, "args": kw,
        "result": {"hits": [{"chunk_id": 42}]},
    }

    res = mod.agent_answer("正官是什么意思？", api_key="sk-test")

    assert res["can_answer"] is True
    assert res["invalid_output"] is False
    assert res["citations_chunk_ids"] == [42]
    assert res["steps"] == 1
    # 第一次尝试 2 次模型调用（工具轮 + 非 JSON 终稿），重跑 1 次
    assert res["llm_calls"] == 3
    # 重跑前确实把原始输出和纠正 observation 追加进了上下文
    retry_messages = api.calls[2]["messages"]
    assert retry_messages[-2] == {"role": "assistant", "content": "这是一段解释，不是 JSON"}
    assert "不要再调用工具" in retry_messages[-1]["content"]
    assert "raw" not in res


# --------------------------------------------------------------------------- #
# 6. 两次终稿解析都失败：invalid_output=True 且 raw 保留
# --------------------------------------------------------------------------- #
def test_final_json_parse_failure_twice_keeps_raw_output(agent_env):
    mod, stub_rag, stub_tools = agent_env
    api = FakeAPI([
        {"content": "第一次：这不是 JSON"},
        {"content": "第二次：仍然不是 JSON"},
    ])
    stub_rag._chat_message = api

    res = mod.agent_answer("问", api_key="sk-test")

    assert res["can_answer"] is None
    assert res["invalid_output"] is True
    assert res["error"] == "JSON 解析失败"
    # 保留最后一次的原始输出，便于线上定位模型到底输出了什么
    assert res["raw"] == "第二次：仍然不是 JSON"
    assert res["trace"] == []
    assert res["llm_calls"] == 2
    assert len(api.calls) == 2
    assert "不要再调用工具" in api.calls[1]["messages"][-1]["content"]


# --------------------------------------------------------------------------- #
# 7. 步数预算用尽：强制拒答，trace 长度 == max_steps
# --------------------------------------------------------------------------- #
def test_step_budget_exhaustion_returns_refusal(agent_env):
    mod, stub_rag, stub_tools = agent_env
    api = FakeAPI([
        {"content": "", "tool_calls": [_tool_call("c1", "search_classics", {"query": "甲"})]},
        {"content": "", "tool_calls": [_tool_call("c2", "search_classics", {"query": "乙"})]},
        {"content": "", "tool_calls": [_tool_call("c3", "search_classics", {"query": "丙"})]},
        # 预算用完后不再传 tools，模型仍不肯给 JSON
        {"content": "预算用完了"},
        {"content": "重跑一次还是不给 JSON"},
    ])
    stub_rag._chat_message = api
    stub_tools.call = lambda name, **kw: {
        "ok": True, "tool": name, "args": kw, "result": {"hits": []},
    }

    res = mod.agent_answer("问", max_steps=3, api_key="sk-test")

    assert res["can_answer"] is False
    assert "步数用尽" in res["refusal_reason"]
    assert res["answer"] == REFUSAL
    assert len(res["trace"]) == 3
    assert res["steps"] == 3
    assert [t["action"] for t in res["trace"]] == [
        "search_classics", "search_classics", "search_classics"]
    # 第 4 次请求起不再给工具，模型没有机会再多调一次
    assert api.calls[3]["tools"] is None


# --------------------------------------------------------------------------- #
# 8. 历史裁剪的信息损失边界
# --------------------------------------------------------------------------- #
def test_history_trimming_drops_oldest_and_marks_truncation():
    # 4 轮 > 默认 MAX_TURNS：只保留最近 3 轮，最旧的一问一答整轮丢掉
    history = []
    for i in range(1, 5):
        history.append({"role": "user", "content": "问题%d" % i})
        history.append({"role": "assistant", "content": "回答%d" % i})

    got = conversation.normalize_history(history)
    assert len(got) == conversation.MAX_TURNS * 2
    assert [m["content"] for m in got] == [
        "问题2", "回答2", "问题3", "回答3", "问题4", "回答4"]
    assert got[-1]["content"] == "回答4"          # 最新一条一定保留
    assert all(m["content"] != "问题1" for m in got)

    # 单条超长：保留开头（通常含主题），按字符预算截断并以「…」标记
    long_text = "主" * 300
    trimmed = conversation.normalize_history(
        [{"role": "user", "content": long_text}], max_turns=1, max_chars=50)
    assert len(trimmed) == 1
    text = trimmed[0]["content"]
    assert len(text) == 50
    assert text.startswith("主")
    assert text.endswith("…")
    assert text[:-1] == "主" * 49

    # 历史进入 prompt 时必须显式声明不能当证据
    block = conversation.history_block(got)
    assert "不作为回答证据" in block
    assert "回答4" in block


# --------------------------------------------------------------------------- #
# 9. 记忆块的信息损失边界
# --------------------------------------------------------------------------- #
def test_memory_block_truncation_boundaries():
    """锁定信息损失边界：记忆块条数有上限，单条 value 有字符上限。

    条数上限是设计（MAX_MEMORIES=8）；value 截断属于「知道会丢信息」的限制，
    截断处必须带「…」作为信息损失标记，否则模型会把半句话当成用户原话。
    """
    memories = [
        {"kind": "preference", "key": "key%d" % i, "value": "value%d" % i}
        for i in range(12)
    ]
    block = conversation.memory_block(memories)

    assert "不作为回答证据" in block
    lines = [line for line in block.splitlines() if line.startswith("- ")]
    assert len(lines) == conversation.MAX_MEMORIES   # 只取前 8 条
    assert "key0" in block and "key7" in block
    assert "key8" not in block and "key11" not in block

    # 单条 value 超过 200 字符：截断到 200，并以「…」标记信息损失
    long_value = "甲" * 250
    one = conversation.memory_block(
        [{"kind": "fact", "key": "birth", "value": long_value}])
    line = next(item for item in one.splitlines() if item.startswith("- "))
    value_part = line.split(": ", 1)[1]
    assert len(value_part) == 200
    assert value_part.endswith("…")


# --------------------------------------------------------------------------- #
# 10. 被拒绝 / 失败的调用：进 trace 复盘，但不能变成引用证据
# --------------------------------------------------------------------------- #
def test_denied_and_failed_tool_calls_are_traced_but_not_citation_evidence(agent_env):
    mod, stub_rag, stub_tools = agent_env
    api = FakeAPI([
        {"content": "", "tool_calls": [
            _tool_call("c1", "mcp__remote__delete_all", {"book": "全部"}),
        ]},
        {"content": "", "tool_calls": [
            _tool_call("c2", "search_classics", {"query": "正官"}),
        ]},
        # 模型声称引用 99，但本次没有任何成功工具返回过 chunk
        {"content": json.dumps(
            {"can_answer": False, "answer": "", "citations": [99],
             "refusal_reason": "工具不可用"},
            ensure_ascii=False)},
    ])
    stub_rag._chat_message = api

    def permission(name):
        if name == "mcp__remote__delete_all":
            return {"allowed": False, "tier": "side_effect",
                    "reason": "工具 %s 属于 side_effect，需要用户确认后执行" % name}
        return {"allowed": True, "tier": "read", "reason": None}

    stub_tools.permission = permission
    executed = []

    def fake_call(name, **kw):
        executed.append((name, kw))
        if name == "search_classics":
            raise RuntimeError("tool backend crashed")
        return {"ok": True}

    stub_tools.call = fake_call

    # max_steps=2：拒绝 + 异常两次尝试各占一步，agent 仍要能产出 JSON
    res = mod.agent_answer("问", max_steps=2, api_key="sk-test")

    # 权限拒绝的工具一次都没执行；异常工具执行了但失败
    assert executed == [("search_classics", {"query": "正官"})]
    assert res["steps"] == 2
    assert len(res["trace"]) == 2

    denied, failed = res["trace"]
    assert denied["action"] == "mcp__remote__delete_all"
    assert denied["ok"] is False
    assert "确认" in denied["error"]
    assert denied["args"] == {"book": "全部"}   # 参数保留，用户确认后可按原参数重试

    assert failed["action"] == "search_classics"
    assert failed["ok"] is False
    assert "RuntimeError" in failed["error"]

    # 失败结果不能变成引用证据：seen 为空，99 被判为无效引用
    assert res["retrieved_chunk_ids"] == []
    assert res["citations_chunk_ids"] == []
    assert res["invalid_citations"] == [99]
    assert res["can_answer"] is False
    assert res["answer"] == REFUSAL
    assert res["tool_mode"] == "function"
