# -*- coding: utf-8 -*-
"""SSE 帧与事件流的最小工具。

`api.py` 和 `api_conversations.py` 都要返回逐 token 的流，协议必须逐字节一致：
- 每帧 `event: <name>\\ndata: <json>\\n\\n`；
- 空闲超过 `SSE_HEARTBEAT` 秒发一行注释，代理和浏览器才知道连接还活着；
- 客户端断开时取消后台生成任务，否则 200 个连接会留下 200 个孤儿协程。
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
from typing import Any, Awaitable, Callable

SSE_HEARTBEAT = float(os.environ.get("MINGLI_SSE_HEARTBEAT", "15"))

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    # Nginx 不缓冲，否则逐 token 会变成一次性返回
    "X-Accel-Buffering": "no",
}


def sse_frame(event: str, data: dict[str, Any]) -> str:
    return "event: {}\ndata: {}\n\n".format(event, json.dumps(data, ensure_ascii=False))


async def sse_source(producer: Callable[[], Awaitable[None]],
                     queue: "asyncio.Queue[str | None]"):
    """把「生产任务 + 队列」变成可以直接交给 StreamingResponse 的异步生成器。

    producer 负责往队列里塞帧，结束时塞一个 None 作为哨兵。
    """
    task = asyncio.create_task(producer())
    try:
        while True:
            try:
                frame = await asyncio.wait_for(queue.get(), timeout=SSE_HEARTBEAT)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
                continue
            if frame is None:
                break
            yield frame
    finally:
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
