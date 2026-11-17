# -*- coding: utf-8 -*-
"""把排盘结果带进对话，作为「已算好的事实」而不是检索证据。

为什么单独一个模块：聊天和排盘解读对盘面的用法不一样。

- `fortune/interpret.py` 是**整段解读**：盘面是主题，古籍片段只是术语材料。
- 这里是**追问**：用户已经在排盘页拿到了盘，接着问「那我这盘适合什么方向」。
  盘面进 prompt，但引用仍然只能来自本轮检索到的片段——盘面本身不是出处，
  它只是一张算好的表。

三条边界写死在代码里：

1. 只收前端传来的固定结构（bazi / astro / tarot），大小有上限；
2. 盘面只做压缩后进 prompt，不让模型「重算」或补盘面里没有的星体神煞；
3. 有盘面时检索问句要带上盘面关键词，否则「我这盘」这类问法检索不到东西。
"""
from __future__ import annotations

import json

MAX_CHART_BYTES = 16 * 1024
KINDS = ("bazi", "astro", "tarot")

# 进 system prompt 的一条规则：和原有规则并存，不替换。
CHART_RULE = (
    "本轮附带【盘面】。盘面是程序算出的既定事实：可以据此说明这张盘的情况，"
    "但不得修改、不得重新推算、不得补充盘面里没有的星体或神煞。"
    "盘面不是出处——引用编号仍然只能来自本轮检索到的片段，不能拿盘面当引用依据。"
)


def normalize(candidate):
    """校验并返回盘面；不合法一律返回 None，让调用方退化成普通问答。

    宁可少一个功能，也不要让一个半截盘面进 prompt——模型会照着残缺字段编。
    """
    if not isinstance(candidate, dict):
        return None
    if candidate.get("kind") not in KINDS:
        return None
    try:
        raw = json.dumps(candidate, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return None
    if len(raw.encode("utf-8")) > MAX_CHART_BYTES:
        return None
    # 用解读模块的字段白名单试压一遍：缺字段的盘在这里就淘汰，
    # 不会等到拼 prompt 时才 KeyError。
    try:
        from fortune.interpret import _payload

        payload = _payload(candidate)
    except Exception:
        return None
    if not isinstance(payload, dict) or not payload:
        return None
    return candidate


def prompt_block(chart):
    """压缩成一段 prompt 文本。chart 不合法时返回空串。"""
    chart = normalize(chart)
    if chart is None:
        return ""
    try:
        from fortune.interpret import _payload

        payload = _payload(chart)
    except Exception:
        return ""
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    return (
        "【盘面】\n"
        "（以下由程序按历法算出，是既定事实：可以解释，不能修改或补项；"
        "盘面本身不是引用依据。）\n" + body
    )


def retrieval_query(chart, question):
    """盘面关键词 + 用户问题，只用于检索，不展示给用户。

    「我这个八字适合什么方向」里的「我这个」对检索没有信息量；
    补上日主、十神、五行之后，检索才可能命中相关的古籍段落。
    """
    chart = normalize(chart)
    if chart is None:
        return (question or "").strip()
    try:
        from fortune.interpret import _retrieval_query

        return _retrieval_query(chart, question)
    except Exception:
        return (question or "").strip()


def system_prompt(base, chart):
    """有盘面时在 system prompt 末尾追加一条规则；没有就原样返回。"""
    if normalize(chart) is None:
        return base
    return base.rstrip() + "\n\n" + CHART_RULE + "\n"
