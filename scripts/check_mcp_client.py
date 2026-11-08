# -*- coding: utf-8 -*-
"""端到端验证 MCP client：起一个外部 MCP server，发现工具，调一次。

默认挂载本仓库自己的 `src/mcp_server.py`（stdio 子进程）——它同时验证了
server 和 client 两侧的协议互通，且不需要联网、不需要额外依赖。

    python scripts/check_mcp_client.py
    python scripts/check_mcp_client.py --call mcp__classics__search_classics \
        --args '{"query": "羊刃", "k": 2}'

也可以挂第三方 server：

    echo '{"servers":{"time":{"transport":"stdio","command":"uvx",
      "args":["mcp-server-time"]}}}' > /tmp/mcp.json
    python scripts/check_mcp_client.py --config /tmp/mcp.json \
        --call mcp__time__get_current_time --args '{"timezone":"Asia/Shanghai"}'
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import mcp_client  # noqa: E402


def _self_mount_config() -> str:
    """生成一份临时配置，把本仓库的 MCP server 当成外部 server 挂上。"""
    cfg = {
        "servers": {
            "classics": {
                "transport": "stdio",
                "command": sys.executable,
                "args": [str(ROOT / "src" / "mcp_server.py")],
                "cwd": str(ROOT),
            }
        }
    }
    fd, path = tempfile.mkstemp(prefix="mingli-mcp-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False)
    return path


def main() -> int:
    # Windows 终端默认 GBK，中文书名会变乱码；统一按 UTF-8 输出
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--config", help="MCP 配置文件；不传则挂载本仓库的 server")
    ap.add_argument("--call", help="要调用的工具全名，如 mcp__classics__list_books")
    ap.add_argument("--args", default="{}", help="调用参数，JSON 字符串")
    ap.add_argument("--timeout", type=float, default=60.0)
    args = ap.parse_args()

    path = args.config or _self_mount_config()
    configs = mcp_client.load_config(path)
    if not configs:
        print("配置里没有可用的 server：%s" % path, file=sys.stderr)
        return 2

    registry = mcp_client.MCPRegistry(configs)
    tools = registry.describe()
    if not tools:
        print("没有发现任何工具；错误：%s" % registry.errors, file=sys.stderr)
        return 1

    print(json.dumps({
        "config": path,
        "servers": [c.name for c in configs],
        "tools": tools,
        "errors": registry.errors,
    }, ensure_ascii=False, indent=2))

    if not args.call:
        return 0

    if not registry.has(args.call):
        print("工具不存在：%s" % args.call, file=sys.stderr)
        return 1
    try:
        kwargs = json.loads(args.args)
    except ValueError as exc:
        print("--args 不是合法 JSON：%s" % exc, file=sys.stderr)
        return 2
    if not isinstance(kwargs, dict):
        print("--args 必须是 JSON 对象", file=sys.stderr)
        return 2

    result = registry.call(args.call, kwargs)
    print(json.dumps(result, ensure_ascii=False)[:2000])
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
