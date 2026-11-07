# -*- coding: utf-8 -*-
"""`rag._chat` 的响应边界：空 JSON / 错误 JSON 不能变成 AttributeError。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import rag  # noqa: E402
import usage  # noqa: E402


class FakeResp:
    def __init__(self, payload, status_code=200, text=""):
        self.payload = payload
        self.status_code = status_code
        self.text = text

    def json(self):
        return self.payload


def _post(payload, status_code=200, text=""):
    return lambda *args, **kwargs: FakeResp(payload, status_code, text)


def test_null_payload_raises_clear_error(monkeypatch):
    monkeypatch.setattr(rag.requests, "post", _post(None))
    with pytest.raises(RuntimeError, match="空/非对象"):
        rag._chat([{"role": "user", "content": "hi"}], api_key="k")


def test_error_payload_raises_clear_error(monkeypatch):
    monkeypatch.setattr(rag.requests, "post", _post({"error": {"message": "bad"}}))
    with pytest.raises(RuntimeError, match="DeepSeek 返回错误"):
        rag._chat([{"role": "user", "content": "hi"}], api_key="k")


def test_http_400_surfaces_api_body(monkeypatch):
    """400 只抛状态码没法定位；必须把 API 说的原因带出来。"""
    body = '{"error": {"message": "prompt must contain the word json"}}'
    monkeypatch.setattr(rag.requests, "post", _post({}, status_code=400, text=body))
    with pytest.raises(RuntimeError, match="HTTP 400.*word json"):
        rag._chat([{"role": "user", "content": "hi"}], api_key="k")


def test_valid_payload_returns_content_and_records_usage(monkeypatch):
    payload = {
        "choices": [{"message": {"content": "ok"}}],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 2,
            "total_tokens": 12,
            "prompt_tokens_details": {"cached_tokens": 4},
        },
    }
    monkeypatch.setattr(rag.requests, "post", _post(payload))
    usage.reset()
    assert rag._chat([{"role": "user", "content": "hi"}], api_key="k") == "ok"
    snap = usage.snapshot()
    assert snap["total_tokens"] == 12
    assert snap["cached_tokens"] == 4
    assert snap["llm_calls"] == 1
