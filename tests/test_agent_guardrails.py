# -*- coding: utf-8 -*-
"""Agent 出口约束的单元测试（不加载 BGE-M3、不调 API）。

`agent.py` 在导入时会 import tools/rag；这里先把它们替换成最小 stub，
只测 `_finalize` 的引用白名单与拒答逻辑，保证 CI 里不需要模型权重。

stub 只在加载被测模块期间生效，加载完立刻还原 sys.modules，
否则会把后续测试模块里的 rag 也替换成 namespace，造成测试之间互相污染。
"""
import importlib.util
import sys
import types
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"


@pytest.fixture(scope="module")
def agent_mod():
    names = ("tools", "rag", "agent")
    saved = {name: sys.modules.get(name) for name in names}

    sys.modules["tools"] = types.SimpleNamespace(call=lambda *a, **k: {"ok": True})
    sys.modules["rag"] = types.SimpleNamespace(
        REFUSAL_TEXT="语料中没有足够的依据回答这个问题。",
        _chat=lambda *a, **k: "",
        _parse_json=lambda raw: {},
    )

    spec = importlib.util.spec_from_file_location("agent_under_test", SRC / "agent.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    for name, old in saved.items():
        if old is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = old
    return mod


def test_citation_whitelist_keeps_only_seen_ids(agent_mod):
    res = agent_mod._finalize(
        {"can_answer": True, "answer": "有依据的回答", "citations": [1, 99]},
        seen={1}, trace=[],
    )
    assert res["citations_chunk_ids"] == [1]
    assert res["invalid_citations"] == [99]
    assert res["invalid_output"] is True


def test_claiming_answer_without_valid_citation_is_invalid(agent_mod):
    res = agent_mod._finalize(
        {"can_answer": True, "answer": "看起来像答案", "citations": [99]},
        seen={1}, trace=[],
    )
    assert res["citations_chunk_ids"] == []
    assert res["invalid_output"] is True


def test_empty_answer_is_invalid(agent_mod):
    res = agent_mod._finalize(
        {"can_answer": True, "answer": "", "citations": [1]},
        seen={1}, trace=[],
    )
    assert res["invalid_output"] is True


def test_refusal_uses_fixed_text(agent_mod):
    res = agent_mod._finalize(
        {"can_answer": False, "answer": "", "citations": [1]},
        seen={1}, trace=[],
    )
    assert res["can_answer"] is False
    assert res["answer"] == agent_mod.REFUSAL_TEXT
    assert res["citations_chunk_ids"] == []
