# -*- coding: utf-8 -*-
"""远程 embedding 客户端，接口对齐 SentenceTransformer.encode。

`retrieval.py` 里只用到 `model.encode(text, normalize_embeddings=True)`，
这里保持同样的调用形状，检索代码不需要区分本地模型还是远程服务。
"""
from __future__ import annotations

import os
import time

import httpx
import numpy as np

DEFAULT_TIMEOUT = float(os.environ.get("MINGLI_EMBED_TIMEOUT", "15"))
RETRIES = int(os.environ.get("MINGLI_EMBED_RETRIES", "2"))


class EmbeddingError(RuntimeError):
    pass


class RemoteEmbedder:
    backend = "remote"

    def __init__(self, url: str, *, token: str | None = None,
                 timeout: float = DEFAULT_TIMEOUT,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.url = url.rstrip("/")
        self.token = token if token is not None else os.environ.get("MINGLI_EMBED_TOKEN", "")
        self.timeout = timeout
        self._transport = transport
        self._client: httpx.Client | None = None

    @property
    def loaded(self) -> bool:
        # 远程服务的模型是否加载了不归本进程管；health 里单独看远程 /health
        return True

    def _client_or_create(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout, transport=self._transport)
        return self._client

    def encode(self, texts, normalize_embeddings: bool = True, **_: object) -> np.ndarray:
        single = isinstance(texts, str)
        items = [texts] if single else list(texts)
        if not items:
            return np.zeros((0, 0), dtype=np.float32)

        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token

        last_exc: Exception | None = None
        for attempt in range(RETRIES + 1):
            try:
                resp = self._client_or_create().post(
                    self.url + "/embed", json={"texts": items}, headers=headers
                )
                if resp.status_code >= 500:
                    raise EmbeddingError("embedding 服务返回 %d" % resp.status_code)
                if resp.status_code != 200:
                    raise EmbeddingError(
                        "embedding 服务返回 %d：%s" % (resp.status_code, resp.text[:200])
                    )
                vectors = np.asarray(resp.json()["vectors"], dtype=np.float32)
                break
            except (httpx.HTTPError, EmbeddingError, KeyError, ValueError) as exc:
                last_exc = exc
                if attempt >= RETRIES:
                    raise EmbeddingError("embedding 调用失败：%s" % exc) from exc
                time.sleep(0.15 * (attempt + 1))
        else:  # pragma: no cover - 上面的 raise 已经覆盖
            raise EmbeddingError("embedding 调用失败：%s" % last_exc)

        if vectors.ndim == 1:
            vectors = vectors.reshape(1, -1)
        if normalize_embeddings:
            norms = np.linalg.norm(vectors, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            vectors = vectors / norms
        return vectors[0] if single else vectors
