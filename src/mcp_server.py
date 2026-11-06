# -*- coding: utf-8 -*-
"""把 mingli-rag 的检索与排盘工具暴露成 MCP server。

这一层只做协议适配，不复制业务逻辑：每个 tool 都转调 ``tools.call``，
所以 CLI、Agent、MCP 三个入口看到的是同一套参数和同一套错误格式。

运行::

    # stdio（Claude Desktop / Cursor 等宿主用这个）
    python src/mcp_server.py

    # 远程 HTTP（Streamable HTTP，默认 127.0.0.1:8765/mcp）
    MCP_TRANSPORT=streamable-http MCP_PORT=8765 python src/mcp_server.py

MCP 解决的是「工具怎么被发现、怎么被调用」；模型侧仍然需要 function
calling 或 JSON action 协议来表达「我要调哪个工具」。两者不是同一层。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tools
from mcp.server.mcpserver import MCPServer

SERVER_NAME = "mingli-rag"
SERVER_VERSION = "1.0.0"

SERVER_INSTRUCTIONS = """\
这是「古籍原文检索」工具集，覆盖 45 部命理古籍、8,681 个 chunk。

使用约定：
1. 回答古籍内容前必须先调用 search_classics 或 fetch_chunk 取证。
2. 引用只能来自工具实际返回过的 chunk_id；没有证据就明确说没有。
3. search_classics 的 mode：rrf 是默认融合；术语原词优先 bm25；口语转述优先 dense。
4. 排盘工具（draw_bazi / draw_astro / draw_tarot）返回的是确定性的历法/天文/牌面结果，
   只能解释，不能重算，也不能补充盘里没有的星体或神煞。
5. 输出不得用于医疗、法律、投资或人生决策。
"""

server = MCPServer(
    name=SERVER_NAME,
    version=SERVER_VERSION,
    instructions=SERVER_INSTRUCTIONS,
)


def _result(payload: dict) -> dict:
    """统一成 JSON 可序列化的 dict；MCP 会把它放进 structuredContent。"""
    return json.loads(json.dumps(payload, ensure_ascii=False, default=str))


@server.tool(
    name="search_classics",
    description="在全部古籍或指定书内检索原文。返回命中的 chunk_id、书名、卷篇、原文和分数。",
)
def search_classics(
    query: str,
    k: int = 5,
    book: str | None = None,
    mode: Literal["rrf", "dense", "bm25"] = "rrf",
) -> dict:
    """检索古籍原文。

    Args:
        query: 检索问题或关键词。
        k: 返回条数，默认 5。
        book: 书名片段（如「三命通会」）；不传则全库检索。
        mode: rrf=双路融合（默认）；bm25=字面匹配，适合术语；dense=语义匹配，适合口语转述。
    """
    return _result(tools.call("search_classics", query=query, k=k, book=book, mode=mode))


@server.tool(
    name="fetch_chunk",
    description="按 chunk_id 取某条完整原文；可附带前后各一条的摘要，用于判断上下文。",
)
def fetch_chunk(chunk_id: int, with_neighbors: bool = False) -> dict:
    """取完整原文。

    Args:
        chunk_id: search_classics 返回的 chunk_id。
        with_neighbors: 是否附带前后各一条的摘要。
    """
    return _result(tools.call("fetch_chunk", chunk_id=chunk_id, with_neighbors=with_neighbors))


@server.tool(
    name="list_books",
    description="列出库内全部书名及 chunk 数，用于确认某本书是否在语料里。",
)
def list_books() -> dict:
    """列出书名和 chunk 数。"""
    return _result(tools.call("list_books"))


@server.tool(
    name="search_terms",
    description="在术语表里查词条释义，补 BM25 对生僻术语的召回短板。",
)
def search_terms(term: str, limit: int = 5) -> dict:
    """查术语表。

    Args:
        term: 术语，如「羊刃」「飞刃」。
        limit: 最多返回几条。
    """
    return _result(tools.call("search_terms", term=term, limit=limit))


@server.tool(
    name="draw_bazi",
    description="排八字盘（四柱、藏干、十神、五行、大运）。纯历法计算，同一输入结果恒定。",
)
def draw_bazi(
    year: int,
    month: int,
    day: int,
    hour: int = 0,
    minute: int = 0,
    gender: Literal["male", "female"] = "male",
) -> dict:
    """排八字盘。

    Args:
        year/month/day/hour/minute: 出生地当地公历时间（不是 UTC）。
        gender: male / female，只影响大运顺逆与起运岁数。
    """
    return _result(tools.call(
        "draw_bazi", year=year, month=month, day=day,
        hour=hour, minute=minute, gender=gender,
    ))


@server.tool(
    name="draw_astro",
    description="排西方本命盘（整宫制，地心视黄经）。纯天文计算，同一输入结果恒定。",
)
def draw_astro(
    year: int,
    month: int,
    day: int,
    hour: int = 0,
    minute: int = 0,
    tz: float = 8.0,
    lat: float = 39.90,
    lon: float = 116.40,
    city: str = "北京",
) -> dict:
    """排本命星盘。

    Args:
        year/month/day/hour/minute: 出生地当地时间。
        tz: 时区偏移，默认 8.0。
        lat/lon: 纬度/经度，默认北京。
        city: 城市名，仅用于展示。
    """
    return _result(tools.call(
        "draw_astro", year=year, month=month, day=day, hour=hour, minute=minute,
        tz=tz, lat=lat, lon=lon, city=city,
    ))


@server.tool(
    name="draw_tarot",
    description="抽塔罗牌。传 seed 时结果可复现；spread 可选 single / three / cross。",
)
def draw_tarot(
    n: int = 3,
    seed: int | None = None,
    spread: str | None = None,
) -> dict:
    """抽塔罗牌。

    Args:
        n: 抽几张，默认 3。
        seed: 随机种子；固定时结果可复现。
        spread: 牌阵名，可选 single / three / cross。
    """
    return _result(tools.call("draw_tarot", n=n, seed=seed, spread=spread))


def main() -> None:
    transport = os.environ.get("MCP_TRANSPORT", "stdio").strip().lower()
    if transport in ("stdio", ""):
        server.run(transport="stdio")
        return
    if transport not in ("sse", "streamable-http"):
        raise SystemExit(
            "MCP_TRANSPORT 只能是 stdio / sse / streamable-http，收到：%r" % transport
        )
    host = os.environ.get("MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("MCP_PORT", "8765"))
    server.run(transport=transport, host=host, port=port)


if __name__ == "__main__":
    main()
