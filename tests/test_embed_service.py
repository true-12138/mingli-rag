# -*- coding: utf-8 -*-
"""embedding 服务与客户端：微批合并、单条/批量形状、归一化、失败重试。"""
import asyncio
import sys
from pathlib import Path

import httpx
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import embed_client
import embed_service


def test_batcher_merges_concurrent_requests():
    calls = []

    def fake_encode(texts):
        calls.append(len(texts))
        # 每条文本一个固定向量，便于断言顺序
        return np.asarray([[float(i), 1.0] for i in range(len(texts))], dtype=np.float32)

    async def scenario():
        batcher = embed_service.Batcher(fake_encode, max_batch=8, max_wait=0.05)
        results = await asyncio.gather(
            batcher.encode(["a"]),
            batcher.encode(["b", "c"]),
            batcher.encode(["d"]),
        )
        return results

    results = asyncio.run(scenario())
    assert [r.shape[0] for r in results] == [1, 2, 1]
    # 三次请求至少有一次被合并，不是逐条 encode
    assert max(calls) >= 2
    assert sum(calls) == 4


def test_batcher_splits_large_batches():
    calls = []

    def fake_encode(texts):
        calls.append(len(texts))
        return np.ones((len(texts), 3), dtype=np.float32)

    async def scenario():
        batcher = embed_service.Batcher(fake_encode, max_batch=2, max_wait=0.01)
        return await batcher.encode(["a", "b", "c", "d", "e"])

    vectors = asyncio.run(scenario())
    assert vectors.shape == (5, 3)
    assert calls and all(n <= 2 for n in calls)


def test_remote_embedder_shapes_and_normalizes():
    import json

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.read().decode())
        assert payload["texts"]
        vectors = [[3.0, 4.0] for _ in payload["texts"]]
        return httpx.Response(200, json={"vectors": vectors, "dim": 2})

    transport = httpx.MockTransport(handler)
    embedder = embed_client.RemoteEmbedder(
        "http://embed", transport=transport, timeout=1
    )
    one = embedder.encode("千", normalize_embeddings=True)
    assert one.shape == (2,)
    assert np.allclose(one, [0.6, 0.8], atol=1e-6)

    many = embedder.encode(["千", "古"], normalize_embeddings=True)
    assert many.shape == (2, 2)


def test_remote_embedder_retries_then_raises():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500, text="boom")

    transport = httpx.MockTransport(handler)
    embedder = embed_client.RemoteEmbedder(
        "http://embed", transport=transport, timeout=1
    )
    try:
        embedder.encode("q")
    except embed_client.EmbeddingError as exc:
        assert "500" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("应当抛 EmbeddingError")
    assert calls["n"] == embed_client.RETRIES + 1
