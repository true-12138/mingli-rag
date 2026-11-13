# -*- coding: utf-8 -*-
"""MCP client 的单元测试。

不起子进程：连接、list_tools、call_tool 的协议互通由
`scripts/check_mcp_client.py` 端到端验证，这里只测纯逻辑——
配置解析、工具名规范化、schema 转换、结果折叠、注册表分发。
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("mcp")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import mcp_client  # noqa: E402


class _FakeResult:
    def __init__(self, structured=None, texts=(), is_error=False):
        self.structuredContent = structured
        self.content = [SimpleNamespace(text=t, type="text") for t in texts]
        self.isError = is_error


def _fake_tool(name, schema=None, desc="desc"):
    return SimpleNamespace(name=name, description=desc,
                           inputSchema=schema or {"type": "object", "properties": {}})


# --------------------------------------------------------------------------- #
# 配置
# --------------------------------------------------------------------------- #
def test_load_config_dict_and_list(tmp_path):
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({
        "servers": {
            "a": {"transport": "stdio", "command": "python", "args": ["x.py"]},
            "bad": {"transport": "grpc", "command": "x"},
            "nocommand": {"transport": "stdio"},
        }
    }), encoding="utf-8")
    configs = mcp_client.load_config(str(path))
    assert [c.name for c in configs] == ["a"]
    # python 会被替换成当前解释器，venv / 容器里不用改配置
    assert configs[0].command == sys.executable

    path.write_text(json.dumps([
        {"name": "b", "transport": "streamable-http", "url": "http://127.0.0.1:9/mcp"},
        {"transport": "stdio", "command": "x"},
    ]), encoding="utf-8")
    configs = mcp_client.load_config(str(path))
    assert [c.name for c in configs] == ["b"]
    assert configs[0].transport == "streamable-http"


def test_load_config_missing_file_is_empty(tmp_path):
    assert mcp_client.load_config(str(tmp_path / "nope.json")) == []


def test_load_config_expands_env(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_TEST_TOKEN", "s3cret")
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({
        "servers": {"r": {
            "transport": "streamable-http",
            "url": "https://example.com/mcp",
            "headers": {"Authorization": "Bearer ${MCP_TEST_TOKEN}"},
        }}
    }), encoding="utf-8")
    cfg = mcp_client.load_config(str(path))[0]
    assert cfg.headers["Authorization"] == "Bearer s3cret"


def test_load_config_reads_permission_lists(tmp_path):
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({
        "servers": {"r": {
            "transport": "streamable-http",
            "url": "https://example.com/mcp",
            "allow": ["search", "delete_all"],
            "read_only": ["search"],
            "deny": ["delete_all"],
        }}
    }), encoding="utf-8")
    cfg = mcp_client.load_config(str(path))[0]
    assert cfg.read_only == ["search"]
    assert cfg.deny == ["delete_all"]


def test_visible_tools_applies_allow_and_deny():
    cfg = mcp_client.ServerConfig(
        name="r", allow=["search", "delete_all"], deny=["delete_all"])
    listed = [_fake_tool("search"), _fake_tool("delete_all"), _fake_tool("other")]
    assert [t.name for t in mcp_client.visible_tools(cfg, listed)] == ["search"]


def test_registry_tier_defaults_to_side_effect():
    worker = _StubWorker(SimpleNamespace(name="time"))
    reg, full = _registry_with(worker)
    reg._tiers = {full: mcp_client.READ}
    assert reg.tier(full) == mcp_client.READ
    # 没在 read_only 里声明过的外部工具一律按 side_effect 处理
    assert reg.tier("mcp__time__delete_all") == mcp_client.SIDE_EFFECT


# --------------------------------------------------------------------------- #
# 名字与 schema
# --------------------------------------------------------------------------- #
def test_tool_name_is_sanitized_and_bounded():
    name = mcp_client.tool_name("my server.v2", "search/things")
    assert name.startswith("mcp__")
    assert "/" not in name and " " not in name and "." not in name
    assert len(name) <= mcp_client.MAX_TOOL_NAME

    long_name = mcp_client.tool_name("s" * 40, "t" * 60)
    assert len(long_name) <= mcp_client.MAX_TOOL_NAME
    # 不同长名截断后不能撞在一起
    other = mcp_client.tool_name("s" * 40, "t" * 59 + "x")
    assert long_name != other


def test_openai_schema_keeps_inputs():
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "EchoArgs",
        "type": "object",
        "properties": {"text": {"type": "string", "description": "要回显的文本"}},
        "required": ["text"],
    }
    out = mcp_client.openai_schema("time", _fake_tool("echo", schema, "回显工具"))
    fn = out["function"]
    assert out["type"] == "function"
    assert fn["name"] == "mcp__time__echo"
    assert fn["description"] == "回显工具"
    assert "$schema" not in fn["parameters"] and "title" not in fn["parameters"]
    assert fn["parameters"]["properties"]["text"]["type"] == "string"
    assert fn["parameters"]["required"] == ["text"]


def test_openai_schema_defaults_empty_object():
    tool = SimpleNamespace(name="ping", description=None, inputSchema=None)
    params = mcp_client.openai_schema("s", tool)["function"]["parameters"]
    assert params == {"type": "object", "properties": {}}


# --------------------------------------------------------------------------- #
# 结果折叠
# --------------------------------------------------------------------------- #
def test_result_payload_prefers_structured_content():
    payload = mcp_client.result_payload(_FakeResult(structured={"ok": 1}, texts=["ignored"]))
    assert payload == {"ok": True, "result": {"ok": 1}}


def test_result_payload_parses_json_text():
    payload = mcp_client.result_payload(_FakeResult(texts=['{"n": 3}']))
    assert payload == {"ok": True, "result": {"n": 3}}


def test_result_payload_unwraps_tools_envelope():
    # 本仓库 mcp_server 返回 {"ok": true, "tool":..., "result": {...}}
    payload = mcp_client.result_payload(
        _FakeResult(structured={"ok": True, "tool": "list_books", "result": {"n": 45}}))
    assert payload == {"ok": True, "result": {"n": 45}}

    failed = mcp_client.result_payload(
        _FakeResult(structured={"ok": False, "error": "书库里没有这本书"}))
    assert failed["ok"] is False and failed["error"] == "书库里没有这本书"


def test_result_payload_plain_text_and_error():
    assert mcp_client.result_payload(_FakeResult(texts=["hi"])) == {
        "ok": True, "result": {"text": "hi"}}
    bad = mcp_client.result_payload(_FakeResult(texts=["boom"], is_error=True))
    assert bad["ok"] is False and bad["error"] == "boom"


# --------------------------------------------------------------------------- #
# 注册表分发
# --------------------------------------------------------------------------- #
class _StubWorker:
    def __init__(self, cfg, result=None, exc=None):
        self.cfg = cfg
        self._result = result
        self._exc = exc
        self.calls = []

    def call(self, tool, args):
        self.calls.append((tool, args))
        if self._exc is not None:
            raise self._exc
        return self._result


def _registry_with(worker, remote="echo"):
    reg = mcp_client.MCPRegistry([])
    reg._loaded = True  # 跳过真实建连
    cfg = SimpleNamespace(name=worker.cfg.name, transport="stdio")
    worker.cfg = cfg
    full = mcp_client.tool_name(cfg.name, remote)
    reg._schemas = [{"type": "function",
                     "function": {"name": full, "description": "d",
                                  "parameters": {"type": "object", "properties": {}}}}]
    reg._routes = {full: (worker, remote)}
    return reg, full


def test_registry_call_success_and_unknown():
    worker = _StubWorker(SimpleNamespace(name="time"), _FakeResult(texts=['{"now":"12:00"}']))
    reg, full = _registry_with(worker)

    out = reg.call(full, {"tz": "Asia/Shanghai"})
    assert out["ok"] is True
    assert out["result"] == {"now": "12:00"}
    assert out["mcp"] == {"server": "time", "tool": "echo"}
    assert worker.calls == [("echo", {"tz": "Asia/Shanghai"})]

    unknown = reg.call("mcp__nope__x", {})
    assert unknown["ok"] is False and "未挂载" in unknown["error"]


def test_registry_call_turns_exception_into_error():
    worker = _StubWorker(SimpleNamespace(name="time"), exc=RuntimeError("连接断了"))
    reg, full = _registry_with(worker)
    out = reg.call(full, {})
    assert out["ok"] is False
    assert "连接断了" in out["error"]


def test_registry_describe_lists_routes():
    worker = _StubWorker(SimpleNamespace(name="time"))
    reg, full = _registry_with(worker)
    assert reg.describe() == [{
        "name": full, "server": "time", "tool": "echo", "transport": "stdio",
    }]
