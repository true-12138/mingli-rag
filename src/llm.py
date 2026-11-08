# -*- coding: utf-8 -*-
"""异步 LLM 客户端：非流式 + 流式 + 多 key + 并发闸门。

为什么要单独一层：
- 现有 `rag._chat_message` 是同步 `requests`，一条回答会占住线程 40–60 秒；
  要扛 200 个 SSE 连接，必须换成 async。
- 多 key 是并发上限的硬约束：每题约 5 次调用是串行的，20 条并发回答的峰值
  在途约 20–30 个流；单 key 被限流时只能靠换 key 或排队，加 worker 没用。
- 流式响应要能把 `tool_calls` 的增量拼回完整调用，所以事件协议放在这一层，
  上层（tool_loop / agent）不用关心 SSE 分片格式。

事件协议（`stream()` 依次 yield）::

    {"type": "delta", "text": "..."}                     # 正文增量
    {"type": "message", "message": {...}, "usage": {...}} # 最后一次，完整 assistant message

`message` 与 OpenAI 非流式响应里的 message 同构，带 `tool_calls` 时可直接回灌。
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager

import httpx
from dotenv import load_dotenv

# llm 可能先于 rag 被 import（api -> agent -> llm），而 URL/模型名在模块加载时
# 就读环境变量；这里自己加载一次，否则 .env 里的 MINGLI_LLM_URL 会被忽略。
load_dotenv()

DEEPSEEK_URL = os.environ.get("MINGLI_LLM_URL", "https://api.deepseek.com/chat/completions")
MODEL = os.environ.get("MINGLI_LLM_MODEL", "deepseek-chat")

RETRY_STATUS = (429, 500, 502, 503, 504)
RETRY_ATTEMPTS = int(os.environ.get("MINGLI_LLM_RETRIES", "3"))
RETRY_MAX_WAIT = float(os.environ.get("MINGLI_LLM_RETRY_MAX_WAIT", "8"))
PER_KEY_CONCURRENCY = int(os.environ.get("MINGLI_LLM_PER_KEY_CONCURRENCY", "32"))


class LLMError(RuntimeError):
    """带上游状态码与响应体，方便日志和评测直接定位。"""

    def __init__(self, message: str, status: int | None = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


def merge_usage(items) -> dict | None:
    """把一次回答里多轮调用的 usage 合并成一个字典。

    流式路径不使用 `usage` 模块的全局累加器：并发回答会互相污染，
    每个请求必须自己记账。
    """
    items = [u for u in (items or []) if isinstance(u, dict)]
    if not items:
        return None
    keys = ("prompt_tokens", "completion_tokens", "total_tokens",
            "prompt_cache_hit_tokens", "prompt_cache_miss_tokens")
    out = {}
    for k in keys:
        vals = [u.get(k) for u in items if isinstance(u.get(k), (int, float))]
        if vals:
            out[k] = int(sum(vals))
    return out or None


def load_keys() -> list[str]:
    """`DEEPSEEK_API_KEYS`（逗号分隔）优先，其次单个 `DEEPSEEK_API_KEY`。"""
    raw = os.environ.get("DEEPSEEK_API_KEYS") or os.environ.get("DEEPSEEK_API_KEY") or ""
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    return keys


def _retry_delay(resp: httpx.Response | None, attempt: int) -> float:
    if resp is not None:
        raw = resp.headers.get("Retry-After")
        try:
            return min(float(raw), RETRY_MAX_WAIT)
        except (TypeError, ValueError):
            pass
    return min(2.0 ** attempt, RETRY_MAX_WAIT)


def _merge_tool_call(acc: dict[int, dict], frag: dict) -> None:
    """把流式 tool_calls 分片拼成完整调用。

    OpenAI 协议里 name 只在第一片出现，arguments 会分很多片；
    必须按 index 累积，不能按出现顺序覆盖。
    """
    idx = frag.get("index", 0)
    item = acc.setdefault(idx, {"id": "", "type": "function",
                                "function": {"name": "", "arguments": ""}})
    if frag.get("id"):
        item["id"] = frag["id"]
    fn = frag.get("function") or {}
    if fn.get("name"):
        item["function"]["name"] += fn["name"]
    if fn.get("arguments"):
        item["function"]["arguments"] += fn["arguments"]


def _finalize_tool_calls(acc: dict[int, dict]) -> list[dict]:
    calls = []
    for idx in sorted(acc):
        item = acc[idx]
        item["id"] = item["id"] or "call_{}".format(idx)
        item["function"]["arguments"] = item["function"]["arguments"] or "{}"
        calls.append(item)
    return calls


class LLMClient:
    def __init__(self, keys: list[str] | None = None, *, per_key_concurrency: int | None = None,
                 timeout: float = 120.0, transport: httpx.AsyncBaseTransport | None = None):
        self.keys = keys if keys is not None else load_keys()
        self.per_key = per_key_concurrency or PER_KEY_CONCURRENCY
        self.timeout = timeout
        self._transport = transport
        self._sems: dict[str, asyncio.Semaphore] = {}
        self._rr = 0
        # 跨 key failover 的轻量熔断：连续失败到阈值后冷却一段时间
        self._strikes: dict[str, int] = {}
        self._cooldown_until: dict[str, float] = {}
        self.strike_limit = int(os.environ.get("MINGLI_KEY_STRIKE_LIMIT", "3"))
        self.cooldown = float(os.environ.get("MINGLI_KEY_COOLDOWN", "30"))

    def has_key(self) -> bool:
        return bool(self.keys)

    def key_count(self) -> int:
        return len(self.keys)

    def _healthy_keys(self) -> list[str]:
        now = time.time()
        healthy = [k for k in self.keys if self._cooldown_until.get(k, 0.0) <= now]
        # 全都在冷却时不要彻底断供：放开最短的那个，让请求自己去试
        return healthy or list(self.keys)

    def _pick_key(self, explicit: str | None) -> str:
        if explicit:
            return explicit
        if not self.keys:
            raise LLMError(
                "没有找到 DEEPSEEK_API_KEYS / DEEPSEEK_API_KEY。"
                "公网部署请把 key 配到环境变量，不要写进仓库。"
            )
        candidates = self._healthy_keys()
        key = candidates[self._rr % len(candidates)]
        self._rr += 1
        return key

    def _mark_failure(self, key: str, explicit: str | None) -> None:
        if explicit:
            return
        strikes = self._strikes.get(key, 0) + 1
        if strikes >= self.strike_limit:
            self._cooldown_until[key] = time.time() + self.cooldown
            self._strikes[key] = 0
        else:
            self._strikes[key] = strikes

    def _mark_success(self, key: str) -> None:
        self._strikes.pop(key, None)
        self._cooldown_until.pop(key, None)

    def _failover_key(self, explicit: str | None, tried: set[str], current: str) -> str:
        """换一个还没试过的健康 key；没有就回到 current 继续退避重试。"""
        if explicit or len(self.keys) <= 1:
            return current
        candidates = self._healthy_keys()
        for key in candidates:
            if key not in tried:
                tried.add(key)
                return key
        # 所有 key 都试过一轮，清空记录再从 current 的下一个开始
        tried.clear()
        tried.add(current)
        idx = self.keys.index(current) if current in self.keys else -1
        return self.keys[(idx + 1) % len(self.keys)]

    @asynccontextmanager
    async def _slot(self, key: str):
        sem = self._sems.setdefault(key, asyncio.Semaphore(self.per_key))
        async with sem:
            yield

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self.timeout, transport=self._transport)

    @staticmethod
    def _headers(key: str) -> dict[str, str]:
        return {"Authorization": "Bearer {}".format(key), "Content-Type": "application/json"}

    @staticmethod
    def _payload(messages, *, tools=None, tool_choice=None, temperature=0.0,
                 response_format=None, stream=False) -> dict:
        body = {"model": MODEL, "messages": messages, "temperature": temperature}
        if tools:
            body["tools"] = tools
            if tool_choice:
                body["tool_choice"] = tool_choice
        elif response_format is not None:
            body["response_format"] = response_format
        if stream:
            body["stream"] = True
            # 流式默认不回 usage；显式要，否则成本报表会缺一块
            body["stream_options"] = {"include_usage": True}
        return body

    async def complete(self, messages, *, api_key: str | None = None, tools=None,
                       tool_choice=None, temperature: float = 0.0,
                       response_format: dict | None = None) -> tuple[dict, dict | None]:
        """非流式调用，返回 (message, usage)。"""
        key = self._pick_key(api_key)
        tried = {key}
        body = self._payload(messages, tools=tools, tool_choice=tool_choice,
                             temperature=temperature, response_format=response_format)
        last: httpx.Response | None = None
        async with self._client() as client:
            for attempt in range(RETRY_ATTEMPTS):
                try:
                    async with self._slot(key):
                        resp = await client.post(
                            DEEPSEEK_URL, headers=self._headers(key), json=body
                        )
                except httpx.HTTPError as exc:
                    self._mark_failure(key, api_key)
                    if attempt + 1 >= RETRY_ATTEMPTS:
                        raise LLMError("上游连接失败：{}".format(exc)) from exc
                    key = self._failover_key(api_key, tried, key)
                    await asyncio.sleep(_retry_delay(None, attempt))
                    continue
                last = resp
                if resp.status_code in RETRY_STATUS:
                    self._mark_failure(key, api_key)
                    if attempt + 1 < RETRY_ATTEMPTS:
                        key = self._failover_key(api_key, tried, key)
                        await asyncio.sleep(_retry_delay(resp, attempt))
                        continue
                else:
                    self._mark_success(key)
                break
        assert last is not None
        if last.status_code >= 400:
            raise LLMError("DeepSeek HTTP {}：{}".format(last.status_code, last.text[:600]),
                           status=last.status_code, body=last.text)
        try:
            payload = last.json()
        except ValueError as exc:
            # 代理/网关偶尔会用 200 回一页 HTML；爆 JSONDecodeError 上层分不清
            # 是上游坏了还是自己解析错了，统一包成 LLMError。
            raise LLMError("DeepSeek 返回的不是 JSON：{}".format(last.text[:200])) from exc
        if not isinstance(payload, dict) or payload.get("error"):
            raise LLMError("DeepSeek 返回异常：{!r}".format(payload))
        return payload["choices"][0]["message"], payload.get("usage")

    async def stream(self, messages, *, api_key: str | None = None, tools=None,
                     tool_choice=None, temperature: float = 0.0,
                     response_format: dict | None = None):
        """流式调用。yield delta 事件，最后 yield 完整 message。

        重试只发生在「还没吐出任何 delta」时；已经下发正文后再断流，
        重放会导致前端看到重复文本，直接报错更诚实。
        """
        key = self._pick_key(api_key)
        tried = {key}
        body = self._payload(messages, tools=tools, tool_choice=tool_choice,
                             temperature=temperature, response_format=response_format,
                             stream=True)
        content: list[str] = []
        calls: dict[int, dict] = {}
        usage: dict | None = None

        async with self._client() as client:
            for attempt in range(RETRY_ATTEMPTS):
                content.clear()
                calls.clear()
                usage = None
                emitted = False
                retryable = False
                retry_after: float | None = None
                try:
                    async with self._slot(key):
                        async with client.stream(
                            "POST", DEEPSEEK_URL,
                            headers=self._headers(key), json=body,
                        ) as resp:
                            if resp.status_code >= 400:
                                text = (await resp.aread()).decode("utf-8", "replace")
                                self._mark_failure(key, api_key)
                                try:
                                    retry_after = float(resp.headers.get("Retry-After", ""))
                                except (TypeError, ValueError):
                                    retry_after = None
                                if resp.status_code in RETRY_STATUS and attempt + 1 < RETRY_ATTEMPTS:
                                    retryable = True
                                else:
                                    raise LLMError(
                                        "DeepSeek HTTP {}：{}".format(resp.status_code, text[:600]),
                                        status=resp.status_code, body=text)
                            else:
                                self._mark_success(key)
                                async for line in resp.aiter_lines():
                                    if not line or not line.startswith("data:"):
                                        continue
                                    data = line[5:].strip()
                                    if not data or data == "[DONE]":
                                        continue
                                    try:
                                        obj = json.loads(data)
                                    except json.JSONDecodeError:
                                        continue
                                    if obj.get("usage"):
                                        usage = obj["usage"]
                                    choices = obj.get("choices") or []
                                    if not choices:
                                        continue
                                    delta = choices[0].get("delta") or {}
                                    text = delta.get("content") or ""
                                    if text:
                                        content.append(text)
                                        emitted = True
                                        yield {"type": "delta", "text": text}
                                    for frag in delta.get("tool_calls") or []:
                                        _merge_tool_call(calls, frag)
                                message = {"role": "assistant",
                                           "content": "".join(content)}
                                if calls:
                                    message["tool_calls"] = _finalize_tool_calls(calls)
                                yield {"type": "message", "message": message, "usage": usage}
                                return
                except LLMError:
                    raise
                except httpx.HTTPError as exc:
                    self._mark_failure(key, api_key)
                    if emitted or attempt + 1 >= RETRY_ATTEMPTS:
                        raise LLMError("流式连接中断：{}".format(exc)) from exc
                    retryable = True
                if retryable:
                    key = self._failover_key(api_key, tried, key)
                    delay = _retry_delay(None, attempt)
                    if retry_after is not None:
                        # 上游明确要求等待时不能抢跑，否则 429 会一直拦着
                        delay = min(max(retry_after, delay), RETRY_MAX_WAIT)
                    await asyncio.sleep(delay)
                    continue
                break
        raise LLMError("流式请求在重试后仍未建立")


_default: LLMClient | None = None


def default_client() -> LLMClient:
    global _default
    if _default is None:
        _default = LLMClient()
    return _default
