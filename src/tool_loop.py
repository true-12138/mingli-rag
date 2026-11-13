# -*- coding: utf-8 -*-
"""原生 function calling 的公共循环，单 Agent 和多 Agent 的检索员共用。

手写 JSON ReAct（agent.py 原来的实现）把「调哪个工具、参数是什么」压在
一段自由文本里，解析失败就得重来一步；原生 tool_calls 由 API 保证结构，
参数是 JSON 字符串，失败只可能是模型给了错参数，不是格式坏了。

这个循环只负责协议本身：
- 调模型 → 有 tool_calls 就执行并回灌 role=tool → 没 tool_calls 就是终稿
- 工具预算用完时不再传 tools，强迫模型直接输出（JSON 模式兜底）
工具结果怎么记账（trace / 证据 / citation 白名单）由调用方在 on_call 里做。
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import llm
import rag
import tools
from answer_stream import AnswerExtractor

MAX_ROUNDS = 12
BUDGET_ERROR = "步数预算已用完，请直接输出终稿"
TOKEN_ERROR = "token 预算已用完，请直接输出终稿"


def _usage_tokens(usage):
    if not isinstance(usage, dict):
        return 0
    try:
        return max(0, int(usage.get("total_tokens") or 0))
    except (TypeError, ValueError):
        return 0


def _permission_denied(name, args, allow_side_effects, approve=None):
    """side_effect 工具默认不执行；有用户授权回调时再放行。

    放行的优先级：
    1. `allow_side_effects=True`：旧的单次运行开关，保留向后兼容；
    2. `approve(name, args)` 返回 True：调用方已经拿到一次性的、绑定参数的授权；
    3. 其余情况都拒绝，并回一条 `requires_confirmation` 的 observation。

    授权回调抛异常必须按未授权处理。权限层是安全边界，出错时只能收紧不能放宽
    （不 fail-open），否则数据库抖动会变成「有副作用的工具被静默执行」。
    """
    if allow_side_effects:
        return None
    check = getattr(tools, "permission", None)
    if check is None:
        return None
    try:
        verdict = check(name) or {}
    except Exception:  # noqa: BLE001 - 权限层失败按放行处理，错误留给工具本身
        return None
    if verdict.get("allowed", True):
        return None
    if approve is not None:
        try:
            if approve(name, args):
                return None
        except Exception:  # noqa: BLE001 - 授权层出错必须拒绝，不能 fail-open
            pass
    return {
        "ok": False,
        "tool": name,
        "args": args,
        "error": verdict.get("reason") or "该工具未获授权，需要用户确认后执行",
        "tier": verdict.get("tier") or "side_effect",
        "requires_confirmation": True,
    }



def _invoke(name, args):
    """调工具；工具自己抛异常也要变成一条 observation，不能把整个循环带走。"""
    try:
        return tools.call(name, **(args or {}))
    except Exception as exc:  # noqa: BLE001 - 工具是外部实现/外部 server，失败要回给模型
        return {
            "ok": False,
            "tool": name,
            "args": args,
            "error": "工具执行异常（{}）：{}".format(type(exc).__name__, exc),
        }


def _clean_call(call, idx):
    """只保留 OpenAI 协议字段，避免把厂商私有字段回灌给下一轮。"""
    fn = call.get("function") or {}
    return {
        "id": call.get("id") or "call_{}".format(idx),
        "type": "function",
        "function": {
            "name": fn.get("name") or "",
            "arguments": fn.get("arguments") or "{}",
        },
    }


def _parse_args(raw):
    """tool_calls.arguments 是 JSON 字符串。解析失败返回 (None, 错误信息)。"""
    if isinstance(raw, dict):
        return raw, None
    try:
        data = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError) as exc:
        return None, "arguments 不是合法 JSON：{}".format(exc)
    if not isinstance(data, dict):
        return None, "arguments 必须是 JSON 对象"
    return data, None


def run(messages, *, api_key=None, max_calls, schemas, prepare=None,
        on_call=None, counter=None, max_rounds=MAX_ROUNDS,
        max_tokens=None, allow_side_effects=False, approve=None):
    """跑 tool-calling 循环，直到模型不再调用工具。

    messages 会被原地追加（assistant/tool 轮次）。返回 (最终 content, messages, 已用调用数)。
    prepare(name, args) -> args 用于强制/修正参数（如检索员锁定 book）。
    on_call(name, args, result) 用于记 trace、收证据；抛异常会终止循环。
    max_tokens 是本轮运行允许消耗的模型 token 总量；用完后不再传 tools。
    side_effect 工具默认不执行：`allow_side_effects=True`（旧的整轮开关）或
    `approve(name, args) -> bool`（用户确认后的一次性授权）任一放行才执行。
    """
    used = 0
    # 同一 counter 上的多次 run（如终稿 JSON 解析失败后重跑）要接着累计，
    # 否则第二次运行会把第一次花的 token 从账上抹掉。
    used_tokens = (counter or {}).get("tokens_used", 0)
    tokens_out = False
    for _ in range(max_rounds):
        with_tools = used < max_calls and not tokens_out
        msg = rag._chat_message(
            messages,
            tools=schemas if with_tools else None,
            api_key=api_key,
            tool_choice="auto" if with_tools else None,
        )
        if counter is not None:
            counter["llm_calls"] = counter.get("llm_calls", 0) + 1
            usage = msg.get("usage")
            if usage:
                counter.setdefault("usage", []).append(usage)
        used_tokens += _usage_tokens(msg.get("usage"))
        if counter is not None:
            counter["tokens_used"] = used_tokens
        if max_tokens is not None and used_tokens >= max_tokens:
            tokens_out = True

        calls = msg.get("tool_calls") or []
        if not calls:
            return msg.get("content") or "", messages, used
        if not with_tools:
            # 没传 tools 不应该再有 tool_calls；有也当成终稿，不执行。
            return msg.get("content") or "", messages, used

        calls = [_clean_call(c, i) for i, c in enumerate(calls)]
        messages.append({
            "role": "assistant",
            "content": msg.get("content") or "",
            "tool_calls": calls,
        })

        for call in calls:
            name = call["function"]["name"]
            if used >= max_calls or tokens_out:
                # 模型一次给了多个调用，预算只够前面几个。剩下的也要回一条
                # tool 消息，否则下一轮请求会因为 tool_call_id 没有响应而报错。
                result = {"ok": False, "tool": name, "args": None,
                          "error": TOKEN_ERROR if tokens_out else BUDGET_ERROR}
                err = "budget"
            else:
                args, err = _parse_args(call["function"]["arguments"])
                if err is None and prepare is not None:
                    try:
                        args = prepare(name, args) or args
                    except Exception as exc:  # prepare 的错误也回给模型，别让循环崩
                        err = "参数预处理失败：{}".format(exc)
                if err is not None:
                    result = {"ok": False, "tool": name, "args": None, "error": err}
                else:
                    denied = _permission_denied(name, args, allow_side_effects, approve)
                    if denied is not None:
                        result = denied
                        err = "denied"
                    else:
                        result = _invoke(name, args)
            messages.append({
                "role": "tool",
                "tool_call_id": call["id"],
                "content": json.dumps(result, ensure_ascii=False),
            })
            if on_call is not None and err != "budget":
                on_call(name, args if err in (None, "denied") else None, result)
            if err != "budget":
                used += 1
        # 一次返回多个调用时可能超过预算：下一轮 with_tools=False，模型必须收口。
    return "", messages, used


async def arun(messages, *, api_key=None, max_calls, schemas, prepare=None,
               on_call=None, on_delta=None, counter=None, max_rounds=MAX_ROUNDS,
               client=None, max_tokens=None, allow_side_effects=False, approve=None):
    """`run()` 的异步版：用 llm.stream() 逐 token 下发，工具层协议不变。

    `on_delta(text)` 只收最终正文的增量；工具轮如果模型同时吐了正文，
    也会先下发（实测极少见），调用方按「不是最终答案」处理即可。
    """
    client = client or llm.default_client()
    used = 0
    used_tokens = (counter or {}).get("tokens_used", 0)
    tokens_out = False
    for _ in range(max_rounds):
        with_tools = used < max_calls and not tokens_out
        extractor = AnswerExtractor()
        final = None
        async for event in client.stream(
            messages,
            api_key=api_key,
            tools=schemas if with_tools else None,
            tool_choice="auto" if with_tools else None,
            response_format=None if with_tools else {"type": "json_object"},
        ):
            if event["type"] == "delta":
                if on_delta is not None:
                    text = extractor.feed(event["text"])
                    if text:
                        on_delta(text)
            else:
                final = event
        if final is None:
            return "", messages, used
        usage = final.get("usage")
        used_tokens += _usage_tokens(usage)
        if counter is not None:
            counter["llm_calls"] = counter.get("llm_calls", 0) + 1
            counter["tokens_used"] = used_tokens
            if usage:
                counter.setdefault("usage", []).append(usage)
        if max_tokens is not None and used_tokens >= max_tokens:
            tokens_out = True

        msg = final["message"]
        calls = msg.get("tool_calls") or []
        if not calls:
            return msg.get("content") or "", messages, used

        calls = [_clean_call(c, i) for i, c in enumerate(calls)]
        messages.append({
            "role": "assistant",
            "content": msg.get("content") or "",
            "tool_calls": calls,
        })

        for call in calls:
            name = call["function"]["name"]
            if used >= max_calls or tokens_out:
                result = {"ok": False, "tool": name, "args": None,
                          "error": TOKEN_ERROR if tokens_out else BUDGET_ERROR}
                err = "budget"
            else:
                args, err = _parse_args(call["function"]["arguments"])
                if err is None and prepare is not None:
                    try:
                        args = prepare(name, args) or args
                    except Exception as exc:
                        err = "参数预处理失败：{}".format(exc)
                if err is not None:
                    result = {"ok": False, "tool": name, "args": None, "error": err}
                else:
                    denied = _permission_denied(name, args, allow_side_effects, approve)
                    if denied is not None:
                        result = denied
                        err = "denied"
                    else:
                        result = await asyncio.to_thread(_invoke, name, args)
            messages.append({
                "role": "tool",
                "tool_call_id": call["id"],
                "content": json.dumps(result, ensure_ascii=False),
            })
            if on_call is not None and err != "budget":
                on_call(name, args if err in (None, "denied") else None, result)
            if err != "budget":
                used += 1
    return "", messages, used
