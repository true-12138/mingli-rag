# -*- coding: utf-8 -*-
"""大小模型路由：难度规则、档位配置、升级条件、请求体与落库。"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import llm
import rag
import router
from db import repo
from db.base import Base, make_engine
from db.models import Conversation, Run, User


def _clear_router_env(monkeypatch):
    for name in (
        "MINGLI_ROUTER",
        "MINGLI_ROUTER_ESCALATE",
        "MINGLI_ROUTER_ESCALATE_REFUSAL",
        "MINGLI_ROUTER_REFUSAL_MIN_SCORE",
        "MINGLI_ROUTER_THRESHOLD",
        "MINGLI_TIER_SMALL_MODEL",
        "MINGLI_TIER_LARGE_MODEL",
        "MINGLI_TIER_SMALL_THINKING",
        "MINGLI_TIER_LARGE_THINKING",
        "MINGLI_TIER_LARGE_EFFORT",
        "MINGLI_LLM_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)


def test_short_definition_goes_small(monkeypatch):
    _clear_router_env(monkeypatch)
    monkeypatch.setenv("MINGLI_TIER_SMALL_MODEL", "deepseek-flash")
    decision = router.decide("羊刃是什么意思？")
    assert decision.tier == "small"
    assert decision.spec.model == "deepseek-flash"
    assert decision.spec.thinking == "disabled"
    assert decision.score < 3


def test_cross_book_comparison_goes_large(monkeypatch):
    _clear_router_env(monkeypatch)
    monkeypatch.setenv("MINGLI_TIER_LARGE_MODEL", "deepseek-v4-pro")
    decision = router.decide(
        "《子平真诠》和《滴天髓》对用神的取法有什么不同？为什么？"
    )
    assert decision.tier == "large"
    assert decision.spec.model == "deepseek-v4-pro"
    assert decision.spec.thinking == "enabled"
    assert any("跨书比较" in s for s in decision.signals)


def test_intra_book_contrast_word_stays_small(monkeypatch):
    """「不一样」不等于跨书比较：同一本书里昼生/夜生的差别仍是单跳题。"""
    _clear_router_env(monkeypatch)
    decision = router.decide(
        "算命的说我命里带羊刃，这东西还分好几种？白天生和晚上生犯的不一样吗？"
    )
    assert decision.tier == "small"
    assert any("比较倾向" in s for s in decision.signals)
    assert not any("跨书比较" in s for s in decision.signals)


def test_contrast_word_with_book_reference_still_goes_large(monkeypatch):
    _clear_router_env(monkeypatch)
    decision = router.decide("天乙贵人分白天晚上来取，不同书的配法一样吗？")
    assert decision.tier == "large"
    assert any("跨书比较" in s for s in decision.signals)


def test_real_life_decision_is_not_sent_to_large_model(monkeypatch):
    _clear_router_env(monkeypatch)
    decision = router.decide("算命的说我今年能考上公务员，我该不该辞职备考？")
    assert decision.tier == "small"
    assert any("现实决策" in s for s in decision.signals)


def test_forced_tier_overrides_rules(monkeypatch):
    _clear_router_env(monkeypatch)
    assert router.decide("羊刃是什么意思？", tier="large").tier == "large"
    assert router.decide("《子平真诠》和《滴天髓》有什么区别？", tier="small").tier == "small"


def test_router_off_uses_one_model(monkeypatch):
    _clear_router_env(monkeypatch)
    monkeypatch.setenv("MINGLI_ROUTER", "off")
    decision = router.decide("《子平真诠》和《滴天髓》对用神有什么不同？")
    assert decision.tier == "small"
    assert decision.reason == "路由已关闭"
    # 显式指定的档位仍然生效，方便排障时强制打大模型
    assert router.decide("随便问问", tier="large").tier == "large"


def test_non_deepseek_deployment_does_not_guess_a_large_model(monkeypatch):
    _clear_router_env(monkeypatch)
    monkeypatch.setenv("MINGLI_TIER_SMALL_MODEL", "Qwen/Qwen3-8B")
    decision = router.decide("《子平真诠》和《滴天髓》对用神有什么不同？")
    assert decision.tier == "small"
    assert decision.reason == "两档模型相同"
    assert decision.spec.model == "Qwen/Qwen3-8B"


def test_request_fields_only_for_deepseek(monkeypatch):
    _clear_router_env(monkeypatch)
    deepseek = router.spec_for("large")
    assert deepseek.request_fields() == {
        "thinking": {"type": "enabled"},
        "reasoning_effort": "high",
    }
    other = router.ModelSpec("small", "Qwen/Qwen3-8B", thinking="disabled")
    assert other.request_fields() == {}


def test_escalation_only_for_unusable_output(monkeypatch):
    _clear_router_env(monkeypatch)
    assert router.needs_escalation({"can_answer": None})[0] is True
    assert router.needs_escalation({"can_answer": True, "invalid_output": True})[0] is True
    # 拒答默认升级，但要求检索分够高；没有命中或分数不够就照常拒答
    assert router.needs_escalation({"can_answer": False, "invalid_output": False})[0] is False
    assert router.needs_escalation(
        {"can_answer": False, "invalid_output": False},
        hits=[{"rrf_score": 0.091}],
    )[0] is False

    monkeypatch.setenv("MINGLI_ROUTER_ESCALATE_REFUSAL", "off")
    assert router.needs_escalation(
        {"can_answer": False, "invalid_output": False},
        hits=[{"rrf_score": 0.9}],
    )[0] is False

    monkeypatch.delenv("MINGLI_ROUTER_ESCALATE_REFUSAL")
    monkeypatch.setenv("MINGLI_ROUTER_REFUSAL_MIN_SCORE", "0.8")
    assert router.needs_escalation(
        {"can_answer": False, "invalid_output": False},
        hits=[{"score": 0.9}],
    )[0] is True
    assert router.needs_escalation(
        {"can_answer": False, "invalid_output": False},
        hits=[{"score": 0.1}],
    )[0] is False


def test_refusal_escalation_reads_rrf_score_and_defaults_to_010(monkeypatch):
    """检索写的是 rrf_score，阈值不配时按 0.10 判。"""
    _clear_router_env(monkeypatch)
    monkeypatch.setenv("MINGLI_ROUTER_ESCALATE_REFUSAL", "on")
    need, why = router.needs_escalation(
        {"can_answer": False, "invalid_output": False},
        hits=[{"rrf_score": 0.144}, {"rrf_score": 0.091}],
    )
    assert need is True
    assert "0.144" in why
    assert router.needs_escalation(
        {"can_answer": False, "invalid_output": False},
        hits=[{"rrf_score": 0.091}],
    )[0] is False


_HITS = [
    {"chunk_id": 83, "text": "羊刃有六：阴刃、阳刃……", "meta": {"book": "张果星宗"}},
    {"chunk_id": 84, "text": "昼生忌阳刃，夜生忌阴刃。", "meta": {"book": "张果星宗"}},
]


def _patch_rag(monkeypatch, replies):
    """把检索和模型都换成假实现，只验证 answer() 的升级编排。"""
    monkeypatch.setattr(rag, "retrieve_one", lambda *a, **kw: [dict(h) for h in _HITS])
    monkeypatch.setattr(rag, "rewrite_question", lambda q, h, **kw: q)
    calls = []

    def fake_chat(messages, temperature=0.0, api_key=None, model=None, **kwargs):
        calls.append(model)
        return replies[min(len(calls), len(replies)) - 1]

    monkeypatch.setattr(rag, "_chat", fake_chat)
    return calls


def test_answer_escalates_when_small_json_is_unusable(monkeypatch):
    _clear_router_env(monkeypatch)
    # 小模型两次都吐不出 JSON → 升到大模型；大模型一次答对
    calls = _patch_rag(monkeypatch, [
        "这不是 JSON",
        "还是不是 JSON",
        '{"can_answer": true, "answer": "有六种 [1]", "citations": [1]}',
    ])
    out = rag.answer("羊刃是什么？", tier="auto")
    assert calls == ["deepseek-chat", "deepseek-chat", "deepseek-v4-pro"]
    assert out["can_answer"] is True
    assert out["citations_chunk_ids"] == [83]
    route = out["route"]
    assert route["escalated"] is True
    assert route["tier"] == "large"
    assert route["model"] == "deepseek-v4-pro"
    assert [a["tier"] for a in route["attempts"]] == ["small", "large"]
    assert "JSON" in route["escalation_reason"]


def test_answer_does_not_escalate_when_small_is_fine(monkeypatch):
    _clear_router_env(monkeypatch)
    calls = _patch_rag(monkeypatch, [
        '{"can_answer": true, "answer": "有六种 [1]", "citations": [1]}',
    ])
    out = rag.answer("羊刃是什么？", tier="auto")
    assert calls == ["deepseek-chat"]
    assert out["route"]["escalated"] is False
    assert out["route"]["tier"] == "small"


def test_answer_does_not_reask_the_large_model_after_it_fails(monkeypatch):
    """auto 已经判成大模型的题，失败再升级只会用同一档重答，必须拦住。"""
    _clear_router_env(monkeypatch)
    calls = _patch_rag(monkeypatch, ["不是 JSON", "还是不是 JSON"])
    out = rag.answer("天乙贵人分白天晚上来取，不同书的配法一样吗？", tier="auto")
    assert calls == ["deepseek-v4-pro", "deepseek-v4-pro"]
    assert out["route"]["escalated"] is False
    assert out["route"]["tier"] == "large"
    assert out["can_answer"] is None


def _fake_response(body):
    class Resp:
        status_code = 200
        text = ""

        def json(self):
            return {
                "choices": [{"message": {"content": json.dumps(body, ensure_ascii=False)}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            }

    return Resp()


def test_chat_message_sends_model_and_thinking(monkeypatch):
    _clear_router_env(monkeypatch)
    seen = {}

    def fake_post(body, api_key=None):
        seen.update(body)
        return _fake_response({"can_answer": False, "answer": "x", "citations": []})

    monkeypatch.setattr(rag, "_post_chat", fake_post)
    rag._chat_message(
        [{"role": "user", "content": "hi"}],
        model="deepseek-v4-pro",
        thinking="enabled",
        reasoning_effort="high",
    )
    assert seen["model"] == "deepseek-v4-pro"
    assert seen["thinking"] == {"type": "enabled"}
    assert seen["reasoning_effort"] == "high"


def test_async_stream_payload_carries_tier_model(monkeypatch):
    _clear_router_env(monkeypatch)
    captured = {}

    def handler(request):
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            text='data: {"choices":[{"delta":{"content":"{}"}}]}\n\n'
                 'data: {"choices":[{"delta":{},"finish_reason":"stop"}],'
                 '"usage":{"total_tokens":1}}\n\n'
                 "data: [DONE]\n\n",
            headers={"content-type": "text/event-stream"},
        )

    async def run():
        client = llm.LLMClient(keys=["k"], transport=httpx.MockTransport(handler))
        async for _event in client.stream(
            [{"role": "user", "content": "hi"}],
            model="deepseek-v4-pro",
            thinking="enabled",
            reasoning_effort="high",
        ):
            pass

    asyncio.run(run())
    assert captured["model"] == "deepseek-v4-pro"
    assert captured["thinking"] == {"type": "enabled"}
    assert captured["reasoning_effort"] == "high"


def test_finish_run_persists_route(monkeypatch):
    _clear_router_env(monkeypatch)
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        user = User(anonymous_id="anon-router")
        session.add(user)
        session.commit()
        conv = Conversation(id="c" * 32, user_id=user.id, title="t")
        session.add(conv)
        session.commit()
        run = repo.create_run(session, conv, "t" * 32, "rag", "羊刃是什么？")
        repo.finish_run(
            session,
            run,
            {
                "can_answer": True,
                "answer": "x",
                "citations_chunk_ids": [1],
                "route": {
                    "tier": "large",
                    "model": "deepseek-v4-pro",
                    "escalated": True,
                    "reason": "难度 3 ≥ 阈值 3；小模型没有产出可解析的 JSON",
                },
            },
            12.0,
            {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )
        refreshed = session.get(Run, run.id)
        assert refreshed.tier == "large"
        assert refreshed.model == "deepseek-v4-pro"
        assert refreshed.escalated is True
        assert "阈值" in refreshed.route_reason
    Base.metadata.drop_all(engine)
