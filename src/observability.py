# -*- coding: utf-8 -*-
"""请求级可观测性：request id、结构化日志、Prometheus 指标。

三件事共用一个 ASGI 中间件：

- 每个请求分配或沿用 ``X-Request-Id``，并写回响应头；
- request_id 放进 contextvar，JSON 日志自动带上，排查时能把一次请求的
  所有日志串起来；
- 统计请求数、耗时直方图、在途请求数，由 ``/metrics`` 暴露。

指标只存在进程内存里，多 worker 部署时每个进程各算各的——和 usage.py
的选择一致：真正的汇总交给 Prometheus 或日志系统。
"""
from __future__ import annotations

import contextvars
import json
import logging
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

REQUEST_ID: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)

# 只接受客户端传来的安全 id；否则重新生成，避免把奇怪字符写进日志和响应头。
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_REQUEST_ID_HEADER = b"x-request-id"

_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0)


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


def current_request_id() -> str:
    return REQUEST_ID.get()


# ---------- 结构化日志 ----------

class JsonFormatter(logging.Formatter):
    """一行一个 JSON，字段固定，方便 grep 和日志平台解析。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", REQUEST_ID.get()),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = REQUEST_ID.get()
        return True


def configure_logging(level: int = logging.INFO, json_logs: bool | None = None) -> None:
    """配置根 logger。重复调用不会叠加 handler。

    ``MINGLI_LOG_JSON=1`` 时输出 JSON（默认开），设 0 回到人类可读格式。
    """
    if json_logs is None:
        json_logs = os.environ.get("MINGLI_LOG_JSON", "1") != "0"

    root = logging.getLogger()
    if getattr(root, "_mingli_configured", False):
        return

    handler = logging.StreamHandler()
    handler.addFilter(RequestIdFilter())
    if json_logs:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
    root.handlers[:] = [handler]
    root.setLevel(level)
    root._mingli_configured = True  # type: ignore[attr-defined]


# ---------- 指标 ----------

class Metrics:
    """进程内计数器。维度只有 method/path/status，path 用路由模板而不是原始 URL，
    避免 ``/runs/<uuid>`` 这种无限增长的标签把内存撑爆。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests: dict[tuple[str, str, str], int] = {}
        # key -> [总耗时秒, 请求数, 各 bucket 计数]
        self._durations: dict[tuple[str, str], list] = {}
        self._inflight = 0
        self._llm_calls = 0
        self._llm_tokens = 0
        self._started = time.time()

    @property
    def inflight(self) -> int:
        with self._lock:
            return self._inflight

    def reset(self) -> None:
        with self._lock:
            self._requests.clear()
            self._durations.clear()
            self._inflight = 0
            self._llm_calls = 0
            self._llm_tokens = 0

    def begin(self) -> None:
        with self._lock:
            self._inflight += 1

    def end(self) -> None:
        with self._lock:
            self._inflight = max(0, self._inflight - 1)

    def observe_request(self, method: str, path: str, status: int,
                        seconds: float) -> None:
        key = (method, path, str(status))
        dkey = (method, path)
        with self._lock:
            self._requests[key] = self._requests.get(key, 0) + 1
            row = self._durations.get(dkey)
            if row is None:
                row = [0.0, 0, [0] * len(_BUCKETS)]
                self._durations[dkey] = row
            row[0] += seconds
            row[1] += 1
            for i, bound in enumerate(_BUCKETS):
                if seconds <= bound:
                    row[2][i] += 1

    def observe_llm(self, snapshot: dict[str, Any] | None) -> None:
        """把一次问答的 token 用量累加进来；snapshot 为空就跳过。"""
        if not isinstance(snapshot, dict):
            return
        with self._lock:
            self._llm_calls += int(snapshot.get("llm_calls") or 0)
            self._llm_tokens += int(snapshot.get("total_tokens") or 0)

    def render(self) -> str:
        with self._lock:
            requests = dict(self._requests)
            durations = {k: [v[0], v[1], list(v[2])] for k, v in self._durations.items()}
            inflight = self._inflight
            llm_calls = self._llm_calls
            llm_tokens = self._llm_tokens
            uptime = time.time() - self._started

        lines = [
            "# HELP mingli_http_requests_total 按方法、路由和状态码统计的请求数",
            "# TYPE mingli_http_requests_total counter",
        ]
        for (method, path, status), count in sorted(requests.items()):
            lines.append(
                'mingli_http_requests_total{method="%s",path="%s",status="%s"} %d'
                % (_esc(method), _esc(path), _esc(status), count)
            )

        lines += [
            "# HELP mingli_http_request_duration_seconds 请求耗时直方图",
            "# TYPE mingli_http_request_duration_seconds histogram",
        ]
        for (method, path), (total, count, buckets) in sorted(durations.items()):
            labels = 'method="%s",path="%s"' % (_esc(method), _esc(path))
            for bound, seen in zip(_BUCKETS, buckets):
                lines.append(
                    "mingli_http_request_duration_seconds_bucket{%s,le=\"%s\"} %d"
                    % (labels, bound, seen)
                )
            lines.append(
                "mingli_http_request_duration_seconds_bucket{%s,le=\"+Inf\"} %d"
                % (labels, count)
            )
            lines.append(
                "mingli_http_request_duration_seconds_sum{%s} %.6f" % (labels, total)
            )
            lines.append(
                "mingli_http_request_duration_seconds_count{%s} %d" % (labels, count)
            )

        lines += [
            "# HELP mingli_http_inflight 正在处理的请求数",
            "# TYPE mingli_http_inflight gauge",
            "mingli_http_inflight %d" % inflight,
            "# HELP mingli_llm_calls_total 上游模型调用次数",
            "# TYPE mingli_llm_calls_total counter",
            "mingli_llm_calls_total %d" % llm_calls,
            "# HELP mingli_llm_tokens_total 上游模型 token 总数",
            "# TYPE mingli_llm_tokens_total counter",
            "mingli_llm_tokens_total %d" % llm_tokens,
            "# HELP mingli_process_uptime_seconds 进程运行秒数",
            "# TYPE mingli_process_uptime_seconds gauge",
            "mingli_process_uptime_seconds %.1f" % uptime,
        ]
        return "\n".join(lines) + "\n"


def _esc(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


METRICS = Metrics()

_logger = logging.getLogger("mingli.http")


# ---------- 中间件 ----------

class ObservabilityMiddleware:
    """纯 ASGI 中间件：比 BaseHTTPMiddleware 少一层任务包装，不吞异常。"""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope.get("headers") or []).get(_REQUEST_ID_HEADER, b"")
        candidate = incoming.decode("latin-1").strip()
        request_id = candidate if _SAFE_ID.match(candidate) else new_request_id()

        token = REQUEST_ID.set(request_id)
        started = time.perf_counter()
        status = 500
        METRICS.begin()

        async def send_with_id(message: dict) -> None:
            nonlocal status
            if message.get("type") == "http.response.start":
                status = int(message["status"])
                headers = list(message.get("headers") or [])
                headers.append((_REQUEST_ID_HEADER, request_id.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            elapsed = time.perf_counter() - started
            METRICS.end()
            route = scope.get("route")
            path = getattr(route, "path", None) or "unmatched"
            method = scope.get("method", "-")
            METRICS.observe_request(method, path, status, elapsed)
            _logger.info(
                "%s %s status=%d elapsed_ms=%.1f",
                method, path, status, elapsed * 1000,
            )
            REQUEST_ID.reset(token)


def install_observability(app: Any) -> None:
    app.add_middleware(ObservabilityMiddleware)
