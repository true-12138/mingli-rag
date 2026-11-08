# -*- coding: utf-8 -*-
"""独立 embedding 服务：BGE-M3 只在这一处常驻。

为什么不在每个 API worker 里各载一份：4 个 worker × 2 GB 权重，
内存先爆；而且 query 编码是检索侧真正的 CPU 瓶颈，集中起来才能做微批。

启动::

    uvicorn embed_service:app --app-dir src --host 0.0.0.0 --port 8100
    # 客户端侧：MINGLI_EMBED_URL=http://127.0.0.1:8100

接口::

    POST /embed  {"texts": ["...", "..."]}
      -> {"vectors": [[...]], "dim": 1024, "model": "BAAI/bge-m3"}

    GET /health  -> 模型是否已加载、队列深度

并发模型：请求进 asyncio 队列，单个调度协程把同一小窗口内的请求拼成一批，
交给线程里的 `model.encode`。多个请求共享一次矩阵运算，比逐条 encode 快。
单进程即可；要横向扩就起多个实例，由上游负载均衡。
"""
from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager
from typing import Any, Callable, Sequence

import numpy as np
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

MODEL_ID = os.environ.get("MINGLI_EMBED_MODEL", os.environ.get("MINGLI_MODEL_DIR", "BAAI/bge-m3"))
MAX_BATCH = int(os.environ.get("MINGLI_EMBED_MAX_BATCH", "32"))
MAX_WAIT_MS = float(os.environ.get("MINGLI_EMBED_WAIT_MS", "20"))
MAX_QUEUE = int(os.environ.get("MINGLI_EMBED_MAX_QUEUE", "512"))
EMBED_TOKEN = os.environ.get("MINGLI_EMBED_TOKEN", "").strip()

_model = None


def _load_model():
    global _model
    if _model is None:
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(MODEL_ID)
    return _model


def _encode_sync(texts: Sequence[str]) -> np.ndarray:
    model = _load_model()
    vecs = model.encode(
        list(texts), normalize_embeddings=True, show_progress_bar=False
    )
    return np.asarray(vecs, dtype=np.float32)


class Batcher:
    """把并发的小请求合并成一批。单调度协程 + asyncio 队列。"""

    def __init__(
        self,
        encode: Callable[[Sequence[str]], np.ndarray],
        *,
        max_batch: int = MAX_BATCH,
        max_wait: float = MAX_WAIT_MS / 1000.0,
        max_queue: int = MAX_QUEUE,
    ) -> None:
        self._encode = encode
        self._max_batch = max(1, max_batch)
        self._max_wait = max(0.0, max_wait)
        self._queue: asyncio.Queue[tuple[list[str], asyncio.Future]] = asyncio.Queue(
            maxsize=max_queue
        )
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self.batches = 0
        self.items = 0

    @property
    def depth(self) -> int:
        return self._queue.qsize()

    async def _ensure_dispatcher(self) -> None:
        if self._task is not None and not self._task.done():
            return
        async with self._lock:
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._run())

    async def encode(self, texts: Sequence[str]) -> np.ndarray:
        items = list(texts)
        if not items:
            return np.zeros((0, 0), dtype=np.float32)
        if len(items) > self._max_batch:
            # 单次请求也不能超过编码批大小；分块后顺序编码，保持返回顺序
            chunks = [
                await self.encode(items[start:start + self._max_batch])
                for start in range(0, len(items), self._max_batch)
            ]
            return np.concatenate(chunks, axis=0)
        await self._ensure_dispatcher()
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        try:
            self._queue.put_nowait((items, future))
        except asyncio.QueueFull as exc:
            raise RuntimeError("embedding 队列已满") from exc
        return await future

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            first = await self._queue.get()
            batch = [first]
            count = len(first[0])
            deadline = loop.time() + self._max_wait
            while count < self._max_batch:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    break
                try:
                    item = await asyncio.wait_for(self._queue.get(), timeout=remaining)
                except asyncio.TimeoutError:
                    break
                if count + len(item[0]) > self._max_batch:
                    # 放回去，下一轮从它开始；避免拼出超过模型批大小的矩阵
                    self._queue.put_nowait(item)
                    break
                batch.append(item)
                count += len(item[0])

            flat = [text for texts, _ in batch for text in texts]
            self.batches += 1
            self.items += len(flat)
            try:
                vectors = await asyncio.to_thread(self._encode, flat)
                vectors = np.asarray(vectors, dtype=np.float32)
                if vectors.shape[0] != len(flat):
                    raise RuntimeError(
                        "编码条数 {} 与请求 {} 不一致".format(vectors.shape[0], len(flat))
                    )
                offset = 0
                for texts, future in batch:
                    chunk = vectors[offset:offset + len(texts)]
                    offset += len(texts)
                    if not future.done():
                        future.set_result(chunk)
            except Exception as exc:  # noqa: BLE001 - 整批失败要逐个回传
                for _, future in batch:
                    if not future.done():
                        future.set_exception(exc)


_BATCHER: Batcher | None = None


def get_batcher() -> Batcher:
    global _BATCHER
    if _BATCHER is None:
        _BATCHER = Batcher(_encode_sync)
    return _BATCHER


def _check_token(authorization: str | None = Header(default=None)) -> None:
    if not EMBED_TOKEN:
        return
    expected = "Bearer " + EMBED_TOKEN
    if authorization != expected:
        raise HTTPException(status_code=401, detail="embedding token 不正确")


class EmbedRequest(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=MAX_BATCH)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="mingli-embed", version="1.0.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, Any]:
    batcher = get_batcher()
    return {
        "status": "ok",
        "model": MODEL_ID,
        "loaded": _model is not None,
        "queue_depth": batcher.depth,
        "batches": batcher.batches,
        "items": batcher.items,
    }


@app.post("/embed", dependencies=[Depends(_check_token)])
async def embed(req: EmbedRequest) -> dict[str, Any]:
    started = time.perf_counter()
    vectors = await get_batcher().encode(req.texts)
    return {
        "vectors": vectors.tolist(),
        "dim": int(vectors.shape[1]) if vectors.ndim == 2 else 0,
        "model": MODEL_ID,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
    }
