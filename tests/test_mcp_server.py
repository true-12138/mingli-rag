# -*- coding: utf-8 -*-
"""MCP server 的协议层测试。

不启动子进程，也不走 stdio：直接调用 MCPServer 的 list_tools / call_tool，
验证「工具被发现」和「参数 schema 正确」这两件事。真正的 stdio 互通由
宿主（Claude Desktop / Cursor）负责，不适合放进单元测试。
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import mcp_server  # noqa: E402

EXPECTED = {
    "search_classics",
    "fetch_chunk",
    "list_books",
    "search_terms",
    "draw_bazi",
    "draw_astro",
    "draw_tarot",
}


def _call(name, arguments):
    result = asyncio.run(mcp_server.server.call_tool(name, arguments))
    assert result.is_error is False
    assert result.content, "MCP 工具没有返回 content"
    return json.loads(result.content[0].text)


def test_all_tools_are_registered():
    tools = asyncio.run(mcp_server.server.list_tools())
    assert {t.name for t in tools} == EXPECTED
    assert all(t.description for t in tools), "每个工具都要有描述，否则模型不知道何时用"


def test_search_classics_schema():
    tools = {t.name: t for t in asyncio.run(mcp_server.server.list_tools())}
    schema = tools["search_classics"].input_schema
    assert schema["required"] == ["query"]
    props = schema["properties"]
    assert set(props) == {"query", "k", "book", "mode"}
    # mode 必须是枚举，不能是自由字符串
    assert props["mode"]["enum"] == ["rrf", "dense", "bm25"]


def test_list_books_returns_corpus_summary():
    data = _call("list_books", {})
    assert data["ok"] is True
    assert data["result"]["n_books"] == 45
    assert sum(b["chunks"] for b in data["result"]["books"]) == 8681


def test_draw_tarot_is_reproducible():
    a = _call("draw_tarot", {"n": 3, "seed": 42})
    b = _call("draw_tarot", {"n": 3, "seed": 42})
    assert a == b
    assert len(a["result"]["cards"]) == 3


def test_fetch_chunk_rejects_bad_id():
    data = _call("fetch_chunk", {"chunk_id": 999999})
    assert data["ok"] is False
    assert "chunk_id" in data["error"] or "不存在" in data["error"]
