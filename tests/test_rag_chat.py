# -*- coding: utf-8 -*-
"""`rag._chat` 的响应边界：空 JSON / 错误 JSON 不能变成 AttributeError。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import rag  # noqa: E402
import usage  # noqa: E402


class FakeResp:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def _post(payload):
    return lambda *args, **kwargs: FakeResp(payload)


def test_null_payload_raises_clear_error(monkeypatch):
    monkeypatch.setattr(rag.requests, "post", _post(None))
    with pytest.raises(RuntimeError, match="空/非对象"):
        rag._chat([{"role": "user", "content": "hi"}], api_key="k")


def test_error_payload_raises_clear_error(monkeypatch):
    monkeypatch.setattr(rag.requests, "post", _post({"error": {"message": "bad"}}))
    with pytest.raises(RuntimeError, match="DeepSeek 返回错误"):
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
