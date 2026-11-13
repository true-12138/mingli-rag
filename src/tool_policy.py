# -*- coding: utf-8 -*-
"""工具权限分级：读操作可以直接执行，有副作用的操作必须显式放行。

分级的判据是「会不会改到进程外的状态」，不是「名字听起来像不像查询」：

- read         只读取语料 / 算力结果，不改任何状态。失败最多重试一次。
- side_effect  可能发消息、写日历、建工单、扣款……重复执行有后果。

内置 7 个工具全部是纯函数：检索、读原文、查术语、排盘。同样的输入永远
同样的输出，所以它们都是 read。

外部 MCP 工具默认按 side_effect 处理。配置方确认某个工具只读后，在
`mcp_servers.json` 里用 ``"read_only": ["search", ...]`` 声明，才会放行；
``"deny": [...]`` 则连 schema 都不挂给模型（模型不知道有这个工具）。

默认不执行 side_effect 工具，只回一条 ``requires_confirmation`` 的 observation。
真正的放行需要调用方在用户确认后传 ``allow_side_effects=True``——这是
Action Card 的语义：模型可以提议，但不能自己拍板。
"""
from __future__ import annotations

READ = "read"
SIDE_EFFECT = "side_effect"

# 与 tools.TOOLS 一一对应，`tests/test_tool_policy.py` 会检查没有漏项。
BUILTIN_TIERS = {
    "search_classics": READ,
    "fetch_chunk": READ,
    "list_books": READ,
    "search_terms": READ,
    "draw_bazi": READ,
    "draw_astro": READ,
    "draw_tarot": READ,
}


def evaluate(name, registry=None):
    """判断一次工具调用是否放行。

    返回 ``{"allowed": bool, "tier": str, "reason": str | None}``。
    未知工具不在这里拦截：让 `tools.call` 返回「可用工具有哪些」对模型更有用。
    """
    tier = BUILTIN_TIERS.get(name)
    if tier is None:
        if name.startswith("mcp__") and registry is not None and registry.has(name):
            tier = registry.tier(name)
        else:
            return {"allowed": True, "tier": READ, "reason": None}

    if tier == READ:
        return {"allowed": True, "tier": READ, "reason": None}
    return {
        "allowed": False,
        "tier": SIDE_EFFECT,
        "reason": (
            "工具 %s 属于 side_effect（可能修改外部状态），本次运行未获授权。"
            "不要重复调用；把这一步写进最终答复，告诉用户需要确认后才能执行。" % name
        ),
    }
