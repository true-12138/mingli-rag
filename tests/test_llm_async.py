# -*- coding: utf-8 -*-
"""异步 LLM 客户端：重试、流式增量、tool_calls 拼装。

不依赖 pytest-asyncio：每个用例用 asyncio.run 包一层，
和项目现有测试保持同一套依赖。
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from llm import LLMClient  # noqa: E402


def _client(handler, keys=("k1",)):
    return LLMClient(keys=list(keys), transport=httpx.MockTransport(handler))


def _ok_message(text="ok"):
    return {"choices": [{"message": {"role": "assistant", "content": text}}],
            "usage": {"total_tokens": 5}}


def test_complete_retries_500_then_succeeds():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500, text="internal error")
        return httpx.Response(200, json=_ok_message())

    async def run():
        client = _client(handler)
        client_retry = __import__("llm").RETRY_ATTEMPTS
        assert client_retry >= 2
        message, usage = await client.complete([{"role": "user", "content": "hi"}])
        assert message["content"] == "ok"
        assert usage["total_tokens"] == 5

    asyncio.run(run())
    assert calls["n"] == 2


def test_complete_400_not_retried():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(400, text="bad request")

    async def run():
        client = _client(handler)
        try:
            await client.complete([{"role": "user", "content": "hi"}])
        except Exception as exc:
            assert "HTTP 400" in str(exc)
        else:
            raise AssertionError("400 应该直接抛错")

    asyncio.run(run())
    assert calls["n"] == 1


def _sse(obj) -> bytes:
    return ("data: " + json.dumps(obj, ensure_ascii=False) + "\n\n").encode("utf-8")


def test_stream_yields_deltas_and_final_message():
    body = b"".join([
        _sse({"choices": [{"delta": {"content": '{"answer": "'}}]}),
        _sse({"choices": [{"delta": {"content": "正官"}}]}),
        _sse({"choices": [{"delta": {"content": '"}'}}]}),
        _sse({"choices": [], "usage": {"total_tokens": 9}}),
        b"data: [DONE]\n\n",
    ])

    def handler(request):
        return httpx.Response(200, content=body)

    async def run():
        client = _client(handler)
        events = [e async for e in client.stream([{"role": "user", "content": "hi"}])]
        deltas = [e["text"] for e in events if e["type"] == "delta"]
        final = [e for e in events if e["type"] == "message"][0]
        assert "".join(deltas) == '{"answer": "正官"}'
        assert final["message"]["content"] == '{"answer": "正官"}'
        assert final["usage"]["total_tokens"] == 9

    asyncio.run(run())


def test_stream_assembles_tool_call_fragments():
    body = b"".join([
        _sse({"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "call_1", "type": "function",
             "function": {"name": "search_", "arguments": ""}}]}}]}),
        _sse({"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"name": "classics", "arguments": '{"query":'}}]}}]}),
        _sse({"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": '"正官"}'}}]}}]}),
        b"data: [DONE]\n\n",
    ])

    def handler(request):
        return httpx.Response(200, content=body)

    async def run():
        client = _client(handler)
        events = [e async for e in client.stream(
            [{"role": "user", "content": "hi"}], tools=[{"type": "function"}])]
        message = [e for e in events if e["type"] == "message"][0]["message"]
        call = message["tool_calls"][0]
        assert call["id"] == "call_1"
        assert call["function"]["name"] == "search_classics"
        assert json.loads(call["function"]["arguments"]) == {"query": "正官"}

    asyncio.run(run())
