# -*- coding: utf-8 -*-
"""MCP client：把外部 MCP server 的工具挂到本项目的工具循环上。

和 `mcp_server.py` 是相反方向：

    mcp_server.py   本项目 → 把 7 个工具按 MCP 暴露出去（给 Claude Desktop / Cursor）
    mcp_client.py   本项目 → 连别人的 MCP server，把它的工具当成自己的工具

挂载后，外部工具会出现在 function calling 的 schema 里，名字统一加
`mcp__<server>__` 前缀（避免和内置 7 个工具撞名）；调用仍走 `tools.call`，
所以 trace、错误格式、步数预算和内置工具完全一致。

外部 server 由配置文件声明，不配置就完全不联网、不启动进程——默认关闭。

配置文件（路径来自 `MINGLI_MCP_CONFIG`，默认仓库根目录 `mcp_servers.json`）::

    {
      "servers": {
        "time": {
          "transport": "stdio",
          "command": "uvx",
          "args": ["mcp-server-time"]
        },
        "remote": {
          "transport": "streamable-http",
          "url": "https://example.com/mcp",
          "headers": {"Authorization": "Bearer ${SOME_TOKEN}"},
          "allow": ["search"],
          "read_only": ["search"],
          "deny": ["delete_all"]
        }
      }
    }

说明：
- `command` 写 `python` / `python3` 时替换成当前解释器（`sys.executable`），
  这样 venv / 容器里不用改配置。
- `allow` 是工具白名单，只挂列出的工具；不写表示全挂。
- `read_only` 声明哪些工具只读。外部工具默认按 side_effect 处理，不在
  这个列表里的调用会被 tool_loop 拦下，等用户确认后才执行。
- `deny` 里的工具连 schema 都不挂，模型不知道它存在。
- `env` 会合并进子进程环境（stdio）；`headers` 支持 `${ENV_VAR}` 取值，
  便于把 token 放在环境变量里而不是配置文件里。
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import os
import re
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("mingli.mcp")

from tool_policy import READ, SIDE_EFFECT

PREFIX = "mcp__"
MAX_TOOL_NAME = 64          # OpenAI function name 上限
CONNECT_TIMEOUT = 25.0      # 单个 server 建连 + 初始化
CALL_TIMEOUT = 60.0         # 单次工具调用

_REPO_ROOT = Path(__file__).resolve().parent.parent
_NAME_RE = re.compile(r"[^A-Za-z0-9_-]")


# --------------------------------------------------------------------------- #
# 配置
# --------------------------------------------------------------------------- #
@dataclass
class ServerConfig:
    name: str
    transport: str = "stdio"
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    allow: list[str] | None = None
    read_only: list[str] | None = None
    deny: list[str] | None = None
    timeout: float = CALL_TIMEOUT


def _expand(value: Any) -> Any:
    """把字符串里的 ${VAR} 换成环境变量；没定义的留空串，避免把字面量当 token 发出去。"""
    if isinstance(value, str):
        return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}",
                      lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, list):
        return [_expand(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    return value


def config_path(explicit: str | None = None) -> Path:
    raw = explicit or os.environ.get("MINGLI_MCP_CONFIG") or str(_REPO_ROOT / "mcp_servers.json")
    return Path(raw).expanduser()


def load_config(path: str | None = None) -> list[ServerConfig]:
    """读配置文件；不存在就返回空列表（默认不挂载任何外部 server）。"""
    p = config_path(path)
    if not p.is_file():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("MCP 配置读取失败 %s：%s", p, exc)
        return []

    items = raw.get("servers", raw) if isinstance(raw, dict) else raw
    if isinstance(items, dict):
        entries = []
        for name, cfg in items.items():
            if isinstance(cfg, dict):
                entries.append((name, cfg))
    elif isinstance(items, list):
        entries = [(c.get("name"), c) for c in items if isinstance(c, dict)]
    else:
        logger.warning("MCP 配置格式不认识：期望 servers 字典或列表")
        return []

    configs: list[ServerConfig] = []
    for name, cfg in entries:
        if not name:
            logger.warning("MCP 配置里有一条没有 name，跳过")
            continue
        transport = str(cfg.get("transport") or "stdio").lower()
        if transport not in ("stdio", "streamable-http", "sse", "http"):
            logger.warning("MCP server %s 的 transport=%r 不支持，跳过", name, transport)
            continue
        cfg = _expand(cfg)
        command = cfg.get("command")
        if transport == "stdio":
            if not command:
                logger.warning("MCP server %s 是 stdio，但没写 command，跳过", name)
                continue
            if command in ("python", "python3"):
                command = sys.executable
        else:
            if not cfg.get("url"):
                logger.warning("MCP server %s 是 %s，但没写 url，跳过", name, transport)
                continue
        configs.append(ServerConfig(
            name=str(name),
            transport="streamable-http" if transport in ("http", "sse") else transport,
            command=command,
            args=[str(a) for a in (cfg.get("args") or [])],
            env={str(k): str(v) for k, v in (cfg.get("env") or {}).items()},
            cwd=cfg.get("cwd") or str(_REPO_ROOT),
            url=cfg.get("url"),
            headers={str(k): str(v) for k, v in (cfg.get("headers") or {}).items()},
            allow=list(cfg["allow"]) if cfg.get("allow") else None,
            read_only=list(cfg["read_only"]) if cfg.get("read_only") else None,
            deny=list(cfg["deny"]) if cfg.get("deny") else None,
            timeout=float(cfg.get("timeout") or CALL_TIMEOUT),
        ))
    return configs


# --------------------------------------------------------------------------- #
# 一个 server = 一个常驻 async 任务 + 一条调用队列
# --------------------------------------------------------------------------- #
class _ServerWorker:
    """连接保持、工具调用都在这条 async 任务里完成。

    为什么不直接 run_coroutine_threadsafe(session.call_tool)：stdio / http 的
    连接是 anyio task group 的上下文，必须「谁进谁出」。把连接、list_tools、
    call_tool 全放在同一个协程里，就不会出现 cross-task cancel scope 报错。
    """

    def __init__(self, cfg: ServerConfig):
        self.cfg = cfg
        self.loop: asyncio.AbstractEventLoop | None = None
        self._job_queue: asyncio.Queue | None = None
        self._ready: concurrent.futures.Future = concurrent.futures.Future()
        self.tools: list[Any] = []
        self.error: str | None = None

    # ---- 同步侧 ----------------------------------------------------------
    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        asyncio.run_coroutine_threadsafe(self._main(), loop)
        try:
            self._ready.result(timeout=CONNECT_TIMEOUT)
        except concurrent.futures.TimeoutError:
            self.error = "连接超时（%.0fs）" % CONNECT_TIMEOUT
        except Exception as exc:  # noqa: BLE001 - 单个 server 失败不影响其它
            self.error = "%s: %s" % (type(exc).__name__, exc)

    def call(self, tool: str, args: dict) -> dict:
        if self.loop is None or self._job_queue is None:
            raise RuntimeError(self.error or "server 未连接")
        fut: concurrent.futures.Future = concurrent.futures.Future()
        self.loop.call_soon_threadsafe(
            self._job_queue.put_nowait, (tool, args, fut)
        )
        return fut.result(timeout=self.cfg.timeout)

    # ---- async 侧 --------------------------------------------------------
    async def _main(self) -> None:
        self._job_queue = asyncio.Queue()
        exit_stack = None
        try:
            from contextlib import AsyncExitStack
            from mcp import ClientSession, StdioServerParameters

            async with AsyncExitStack() as stack:
                exit_stack = stack
                if self.cfg.transport == "stdio":
                    from mcp.client.stdio import stdio_client
                    params = StdioServerParameters(
                        command=self.cfg.command or "",
                        args=self.cfg.args,
                        env=self.cfg.env or None,
                        cwd=self.cfg.cwd,
                    )
                    read, write = await stack.enter_async_context(stdio_client(params))
                else:
                    from mcp.client.streamable_http import streamable_http_client
                    read, write = await stack.enter_async_context(
                        streamable_http_client(self.cfg.url or "")
                    )
                session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()

                listed = await session.list_tools()
                tools = list(getattr(listed, "tools", []) or [])
                self.tools = visible_tools(self.cfg, tools)
                self._ready.set_result(True)

                while True:
                    job = await self._job_queue.get()
                    if job is None:
                        break
                    tool, args, fut = job
                    try:
                        result = await session.call_tool(tool, arguments=args)
                    except Exception as exc:  # noqa: BLE001
                        if not fut.cancelled():
                            fut.set_exception(exc)
                    else:
                        if not fut.cancelled():
                            fut.set_result(result)
        except Exception as exc:  # noqa: BLE001
            self.error = "%s: %s" % (type(exc).__name__, exc)
            if not self._ready.done():
                self._ready.set_exception(exc)
            logger.warning("MCP server %s 连接失败：%s", self.cfg.name, self.error)
        finally:
            # 任务结束时把还在排队的调用都唤醒，避免调用方一直等到超时
            if self._job_queue is not None:
                while not self._job_queue.empty():
                    job = self._job_queue.get_nowait()
                    if job is None:
                        continue
                    _, _, fut = job
                    if not fut.done():
                        fut.set_exception(RuntimeError(self.error or "server 连接已关闭"))
            _ = exit_stack


# --------------------------------------------------------------------------- #
# 工具名 / schema 转换
# --------------------------------------------------------------------------- #
def visible_tools(cfg: ServerConfig, listed: list[Any]) -> list[Any]:
    """按 allow / deny 过滤 server 暴露的工具；deny 连 schema 都不挂。"""
    tools = list(listed)
    if cfg.allow:
        allow = set(cfg.allow)
        tools = [t for t in tools if t.name in allow]
    if cfg.deny:
        deny = set(cfg.deny)
        tools = [t for t in tools if t.name not in deny]
    return tools


def tool_name(server: str, tool: str) -> str:
    kind = PREFIX + _NAME_RE.sub("_", server) + "__" + _NAME_RE.sub("_", tool)
    if len(kind) <= MAX_TOOL_NAME:
        return kind
    # 超长就截断，并用短哈希兜底防撞名
    import hashlib
    digest = hashlib.sha1(kind.encode("utf-8")).hexdigest()[:8]
    return kind[:MAX_TOOL_NAME - 9] + "_" + digest


def openai_schema(server: str, tool: Any) -> dict:
    params = getattr(tool, "inputSchema", None) or {}
    if not isinstance(params, dict):
        params = {}
    params = {k: v for k, v in params.items() if k not in ("$schema", "$id", "title")}
    params.setdefault("type", "object")
    params.setdefault("properties", {})
    return {
        "type": "function",
        "function": {
            "name": tool_name(server, tool.name),
            "description": (getattr(tool, "description", None) or tool.name)[:1024],
            "parameters": params,
        },
    }


def result_payload(result: Any) -> dict:
    """把 MCP CallToolResult 折成 tools 层统一的 result dict。"""
    data: Any = None
    structured = getattr(result, "structuredContent", None)
    if structured not in (None, {}):
        data = structured
    else:
        texts = []
        for item in getattr(result, "content", []) or []:
            text = getattr(item, "text", None)
            if text is not None:
                texts.append(text)
        if len(texts) == 1:
            try:
                data = json.loads(texts[0])
            except (TypeError, ValueError):
                data = {"text": texts[0]}
        elif texts:
            data = {"text": "\n".join(texts)}
        else:
            data = {"content": [getattr(i, "type", "unknown")
                                for i in getattr(result, "content", []) or []]}

    # 本项目的 MCP server 返回的就是 tools 层信封 {"ok":..., "result":...}；
    # 拆一层，外部工具和内置工具的 result 结构才一致，模型不用多绕一层。
    if (isinstance(data, dict) and isinstance(data.get("ok"), bool)
            and ("result" in data or "error" in data)):
        if data["ok"]:
            data = data.get("result")
        else:
            return {"ok": False, "error": str(data.get("error") or "MCP 工具返回失败"),
                    "raw": data}

    if getattr(result, "isError", False):
        text = data.get("text") if isinstance(data, dict) else None
        return {"ok": False, "error": text or json.dumps(data, ensure_ascii=False)[:500],
                "raw": data}
    return {"ok": True, "result": data}


# --------------------------------------------------------------------------- #
# 注册表：所有 server 的工具合成一张表
# --------------------------------------------------------------------------- #
class MCPRegistry:
    def __init__(self, configs: list[ServerConfig]):
        self.configs = configs
        self._lock = threading.Lock()
        self._loaded = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._workers: list[_ServerWorker] = []
        self._schemas: list[dict] = []
        self._routes: dict[str, tuple[_ServerWorker, str]] = {}
        self._tiers: dict[str, str] = {}
        self.errors: dict[str, str] = {}

    # ---- 生命周期 --------------------------------------------------------
    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
            self._thread = threading.Thread(
                target=self._run_loop, name="mcp-client", daemon=True
            )
            self._thread.start()
        return self._loop

    def _run_loop(self) -> None:
        assert self._loop is not None
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def load(self) -> None:
        """幂等：并发调用只会真正连一次；单个 server 失败只记日志。"""
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            self._loaded = True
            if not self.configs:
                return
            loop = self._ensure_loop()
            for cfg in self.configs:
                worker = _ServerWorker(cfg)
                worker.start(loop)
                if worker.error and not worker.tools:
                    self.errors[cfg.name] = worker.error
                    continue
                self._workers.append(worker)
                read_only = set(cfg.read_only or [])
                for tool in worker.tools:
                    full = tool_name(cfg.name, tool.name)
                    if full in self._routes:
                        logger.warning("MCP 工具重名，忽略 %s.%s", cfg.name, tool.name)
                        continue
                    self._schemas.append(openai_schema(cfg.name, tool))
                    self._routes[full] = (worker, tool.name)
                    self._tiers[full] = READ if tool.name in read_only else SIDE_EFFECT
                logger.info(
                    "MCP server %s 已挂载 %d 个工具", cfg.name, len(worker.tools)
                )

    # ---- 查询 / 调用 -----------------------------------------------------
    def schemas(self) -> list[dict]:
        self.load()
        return list(self._schemas)

    def has(self, name: str) -> bool:
        self.load()
        return name in self._routes

    def tier(self, name: str) -> str:
        """外部工具默认 side_effect；配置里 read_only 声明过的才是 read。"""
        self.load()
        return self._tiers.get(name, SIDE_EFFECT)

    def call(self, name: str, args: dict) -> dict:
        self.load()
        route = self._routes.get(name)
        if route is None:
            return {"ok": False, "tool": name, "args": args,
                    "error": "未挂载的 MCP 工具：%s" % name}
        worker, remote_name = route
        try:
            result = worker.call(remote_name, args or {})
        except Exception as exc:  # noqa: BLE001 - 工具失败要回给模型，不是让循环崩
            return {"ok": False, "tool": name, "args": args,
                    "error": "MCP 调用失败（%s）：%s" % (worker.cfg.name, exc)}
        payload = result_payload(result)
        if payload["ok"]:
            return {"ok": True, "tool": name, "args": args,
                    "mcp": {"server": worker.cfg.name, "tool": remote_name},
                    "result": payload["result"]}
        return {"ok": False, "tool": name, "args": args,
                "mcp": {"server": worker.cfg.name, "tool": remote_name},
                "error": payload["error"]}

    def describe(self) -> list[dict]:
        self.load()
        return [
            {
                "name": full,
                "server": worker.cfg.name,
                "tool": remote,
                "transport": worker.cfg.transport,
            }
            for full, (worker, remote) in sorted(self._routes.items())
        ]


_REGISTRY: MCPRegistry | None = None
_REGISTRY_LOCK = threading.Lock()


def registry(path: str | None = None) -> MCPRegistry:
    global _REGISTRY
    with _REGISTRY_LOCK:
        if _REGISTRY is None:
            _REGISTRY = MCPRegistry(load_config(path))
        return _REGISTRY


def reset_registry() -> None:
    """测试用：丢掉当前注册表，下次 registry() 重新读配置。"""
    global _REGISTRY
    with _REGISTRY_LOCK:
        _REGISTRY = None
