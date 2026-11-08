# -*- coding: utf-8 -*-
"""验证当前 LLM 配置是否满足本项目的调用契约。

本项目对上游有三条硬要求，换供应商/换模型前先跑这个脚本：

1. `POST /chat/completions` 支持 `stream: true`（逐 token）
2. 支持 `response_format={"type": "json_object"}`（RAG 单轮回答）
3. 支持 `tools` + `tool_calls`（单/多 Agent）

用法::

    python scripts/check_llm.py
    python scripts/check_llm.py --skip-tools

只读环境变量与 `.env`，不打印 key。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except Exception:  # noqa: BLE001 - 没装 dotenv 也能跑，靠 shell 环境变量
    pass

import llm  # noqa: E402


async def check_json_object() -> bool:
    print("[1/2] 流式 + json_object ...", flush=True)
    chunks = 0
    message = None
    try:
        async for event in llm.default_client().stream(
            [{"role": "user", "content": "只输出一个 JSON 对象：{\"answer\": \"ok\"}"}],
            response_format={"type": "json_object"},
        ):
            if event["type"] == "delta":
                chunks += 1
            else:
                message = event["message"]
    except llm.LLMError as exc:
        print("  FAIL status=%s body=%s" % (exc.status, (exc.body or "")[:300]))
        return False
    text = (message or {}).get("content", "")
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        print("  FAIL 返回内容不是 JSON：%r" % text[:200])
        return False
    print("  OK deltas=%d json_keys=%s" % (chunks, sorted(obj)[:5]))
    return True


async def check_tools() -> bool:
    print("[2/2] 流式 + tool_calls ...", flush=True)
    tools = [{
        "type": "function",
        "function": {
            "name": "ping",
            "description": "测试用工具，原样返回参数",
            "parameters": {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
        },
    }]
    message = None
    try:
        async for event in llm.default_client().stream(
            [{"role": "user", "content": "调用 ping 工具，value 设为 ok。"}],
            tools=tools,
            tool_choice="auto",
        ):
            if event["type"] == "message":
                message = event["message"]
    except llm.LLMError as exc:
        print("  FAIL status=%s body=%s" % (exc.status, (exc.body or "")[:300]))
        return False
    calls = (message or {}).get("tool_calls") or []
    if not calls:
        print("  FAIL 没有返回 tool_calls：%r" % ((message or {}).get("content", "")[:200],))
        return False
    print("  OK tool_calls=%s" % [c.get("function", {}).get("name") for c in calls])
    return True


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-tools", action="store_true", help="只验证流式与 json_object")
    args = ap.parse_args()

    client = llm.default_client()
    print("endpoint : %s" % llm.DEEPSEEK_URL)
    print("model    : %s" % llm.MODEL)
    print("keys     : %d" % client.key_count())
    if client.key_count() == 0:
        print("没有配置 DEEPSEEK_API_KEYS / DEEPSEEK_API_KEY")
        return 2

    results = [await check_json_object()]
    if not args.skip_tools:
        results.append(await check_tools())
    print("结果: %s" % ("全部通过" if all(results) else "有失败项"))
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
