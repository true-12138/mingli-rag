# -*- coding: utf-8 -*-
"""7 个工具的 OpenAI function calling 声明。

写成显式 schema 而不是从函数签名反射生成，是为了控制 description——
模型靠它决定「什么时候该调这个工具、query 写什么」，这层信息签名里没有。
`tests/test_tool_schema.py` 会检查 schema 与 tools.TOOLS 一一对应，
避免改了函数忘了改 schema。
"""
from __future__ import annotations

SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_classics",
            "description": (
                "在古籍语料里检索原文片段。返回 chunk_id、书名、篇名和正文。"
                "query 用 2–8 字的术语本身，不要塞整句问题；"
                "查特定书时传 book（书名片段即可，如「子平真诠」指《子平真诠评注》）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索词，2–8 字的术语或别名"},
                    "k": {"type": "integer", "description": "返回条数，默认 5", "default": 5},
                    "book": {"type": "string", "description": "限定书名片段，不传则全库检索"},
                    "mode": {
                        "type": "string",
                        "enum": ["rrf", "dense", "bm25"],
                        "description": "dense=语义；bm25=字面精确术语；rrf=融合（默认）",
                        "default": "rrf",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_chunk",
            "description": (
                "按 chunk_id 取完整原文。命中的是目录/篇名（如「三十一．论正官」）却没有正文时，"
                "用 with_neighbors=true 取相邻段落。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "chunk_id": {"type": "integer", "description": "检索结果里的 chunk_id"},
                    "with_neighbors": {
                        "type": "boolean",
                        "description": "是否同时返回前后各一条", "default": False,
                    },
                },
                "required": ["chunk_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_books",
            "description": "列出语料库里所有书及其 chunk 数。不确定某本书在不在库里时用。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_terms",
            "description": "查术语表，返回该术语的释义。术语表是词典不是原文，不能作为引用出处。",
            "parameters": {
                "type": "object",
                "properties": {
                    "term": {"type": "string", "description": "术语，如「空亡」「天乙贵人」"},
                    "limit": {"type": "integer", "description": "返回条数，默认 5", "default": 5},
                },
                "required": ["term"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "draw_bazi",
            "description": (
                "排八字盘：返回四柱、藏干、十神、五行和大运。纯历法计算，"
                "同样的输入永远同一个盘；返回值是既成事实，不要重算或补充盘里没有的神煞。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "year": {"type": "integer", "description": "公历年"},
                    "month": {"type": "integer", "description": "公历月 1–12"},
                    "day": {"type": "integer", "description": "公历日"},
                    "hour": {"type": "integer", "description": "小时 0–23，不知道就传 0", "default": 0},
                    "minute": {"type": "integer", "description": "分钟 0–59", "default": 0},
                    "gender": {"type": "string", "enum": ["male", "female"], "default": "male"},
                },
                "required": ["year", "month", "day"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "draw_astro",
            "description": (
                "排西方本命星盘（整宫制）：太阳、月亮等行星的星座与宫位、相位。"
                "问星座、月亮落在哪、星盘时用它；它排的不是紫微斗数。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "year": {"type": "integer"},
                    "month": {"type": "integer"},
                    "day": {"type": "integer"},
                    "hour": {"type": "integer", "default": 0},
                    "minute": {"type": "integer", "default": 0},
                    "tz": {"type": "number", "description": "时区，默认 8.0（东八区）", "default": 8.0},
                    "lat": {"type": "number", "description": "纬度，默认北京", "default": 39.90},
                    "lon": {"type": "number", "description": "经度，默认北京", "default": 116.40},
                    "city": {"type": "string", "description": "出生地城市名", "default": "北京"},
                },
                "required": ["year", "month", "day"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "draw_tarot",
            "description": "抽塔罗牌。seed 固定时结果可复现。",
            "parameters": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer", "description": "张数，默认 3", "default": 3},
                    "seed": {"type": "integer", "description": "随机种子，不传则随机"},
                    "spread": {
                        "type": "string",
                        "enum": ["single", "three", "cross"],
                        "description": "牌阵，默认 single",
                    },
                },
            },
        },
    },
]

NAME2SCHEMA = {s["function"]["name"]: s for s in SCHEMAS}
