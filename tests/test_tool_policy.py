# -*- coding: utf-8 -*-
"""工具权限分级：内置工具全是纯函数（read），外部 MCP 工具默认 side_effect。

这里不连 MCP server，只验证分级的判断逻辑与「权限声明」的默认值。
真正的拦截发生在 tool_loop，见 `tests/test_tool_loop.py`。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import tool_policy  # noqa: E402
import tools  # noqa: E402


def test_builtin_tiers_cover_every_tool():
    # 新增内置工具却忘了登记分级时，这里会失败，避免它被默认放行/误拦
    assert set(tool_policy.BUILTIN_TIERS) == set(tools.TOOLS)
    assert all(t == tool_policy.READ for t in tool_policy.BUILTIN_TIERS.values())


def test_builtin_tool_is_allowed():
    verdict = tool_policy.evaluate("search_classics")
    assert verdict["allowed"] is True
    assert verdict["tier"] == tool_policy.READ


def test_unknown_tool_falls_through_to_tools_layer():
    # 未登记的名字交给 tools.call 回「未知工具」，权限层不重复判断
    verdict = tool_policy.evaluate("no_such_tool")
    assert verdict["allowed"] is True


class _Registry:
    def __init__(self, name, tier):
        self._name = name
        self._tier = tier

    def has(self, name):
        return name == self._name

    def tier(self, name):
        return self._tier


def test_mcp_side_effect_is_denied_by_default():
    reg = _Registry("mcp__remote__delete_all", tool_policy.SIDE_EFFECT)
    verdict = tool_policy.evaluate("mcp__remote__delete_all", reg)
    assert verdict["allowed"] is False
    assert verdict["tier"] == tool_policy.SIDE_EFFECT
    # 原因要能让模型看懂「别重试、要用户确认」
    assert "确认" in verdict["reason"]


def test_mcp_read_only_is_allowed():
    reg = _Registry("mcp__remote__search", tool_policy.READ)
    verdict = tool_policy.evaluate("mcp__remote__search", reg)
    assert verdict["allowed"] is True
    assert verdict["tier"] == tool_policy.READ


def test_mcp_unmounted_name_does_not_raise():
    reg = _Registry("mcp__remote__search", tool_policy.READ)
    assert tool_policy.evaluate("mcp__remote__other", reg)["allowed"] is True
