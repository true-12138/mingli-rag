# -*- coding: utf-8 -*-
"""工具授权的端到端测试：提议 → 落库 → 确认拿令牌 → 下一次重放。

不调模型、不联网。仓库层用内存 SQLite；tool_loop 用 stub 替换 rag / tools，
和 `test_tool_loop.py` 的做法一致，避免加载语料和外部 MCP。
"""
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

import api  # noqa: E402
import api_conversations  # noqa: E402
from db import repo  # noqa: E402
from db.base import Base, get_session, make_engine  # noqa: E402

DENY = {
    "allowed": False,
    "tier": "side_effect",
    "reason": "工具需要用户确认后执行",
}


# --------------------------------------------------------------------------- #
# 仓库层 fixture
# --------------------------------------------------------------------------- #
@pytest.fixture()
def db():
    """返回 Session 工厂；每个测试独立内存库。"""
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield Session
    finally:
        Base.metadata.drop_all(engine)


def _user(session, anon="u-approval"):
    return repo.get_or_create_user(session, anon)


def _approve(session, user_id, action_id, **kwargs):
    approved = repo.approve_action(session, user_id, action_id, **kwargs)
    assert approved is not None
    return approved


# --------------------------------------------------------------------------- #
# tool_loop fixture：只验证协议层，不碰真实依赖
# --------------------------------------------------------------------------- #
class FakeAPI:
    def __init__(self, replies):
        self.replies = list(replies)

    def __call__(self, messages, tools=None, temperature=0.0, api_key=None,
                 tool_choice=None):
        return self.replies.pop(0)


def _tool_call(cid, name, args):
    return {
        "id": cid,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
    }


@pytest.fixture
def loop_env():
    names = ("rag", "tools", "tool_loop")
    saved = {n: sys.modules.get(n) for n in names}
    fake_rag = types.SimpleNamespace(_chat_message=None)
    fake_tools = types.SimpleNamespace(call=None, permission=lambda name: DENY)
    sys.modules["rag"] = fake_rag
    sys.modules["tools"] = fake_tools
    sys.modules.pop("tool_loop", None)

    spec = importlib.util.spec_from_file_location(
        "tool_loop_approvals", SRC / "tool_loop.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        yield mod, fake_rag, fake_tools
    finally:
        for name, old in saved.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old


# --------------------------------------------------------------------------- #
# 接口层 fixture
# --------------------------------------------------------------------------- #
def _agent_result(**extra):
    base = {
        "can_answer": True,
        "answer": "测试回答 [1]",
        "citations": [1],
        "citations_chunk_ids": [1],
        "invalid_citations": [],
        "invalid_output": False,
        "refusal_reason": None,
        "retrieved_chunk_ids": [1],
        "rewritten_question": "独立问题",
        "history_turns": 0,
        "llm_calls": 1,
        "trace": [],
        "steps": 0,
    }
    base.update(extra)
    return base


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.delenv("MINGLI_API_TOKEN", raising=False)
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, expire_on_commit=False)

    def override_session():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    api.app.dependency_overrides[get_session] = override_session
    with TestClient(api.app) as test_client:
        yield test_client
    api.app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


def _create_conv(client, anon="anon-1"):
    r = client.post("/v1/conversations", json={}, headers={"X-Anonymous-Id": anon})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _chat_with_pending(client, monkeypatch, anon="anon-1", pending=None,
                       conversation_id=None):
    pending = pending or [{
        "tool": "mcp__remote__delete_all",
        "args": {"book": "全部"},
        "reason": "工具需要用户确认后执行",
    }]

    def fake_agent(question, max_steps=6, api_key=None, history=None, memories=None):
        return _agent_result(pending_actions=pending)

    monkeypatch.setattr(api_conversations.agent, "agent_answer", fake_agent)
    conv_id = conversation_id or _create_conv(client, anon)
    r = client.post(
        f"/v1/conversations/{conv_id}/chat",
        json={"question": "删掉全部", "mode": "agent"},
        headers={"X-Anonymous-Id": anon},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _parse_sse(text):
    frames = []
    for block in text.split("\n\n"):
        event, data = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                event = line[7:].strip()
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if event:
            frames.append((event, data))
    return frames


# --------------------------------------------------------------------------- #
# 仓库层
# --------------------------------------------------------------------------- #
def test_create_pending_action_is_idempotent_for_same_tool_and_args(db):
    """同一用户 + 同一工具 + 同一参数重复提议，只留一条 pending。"""
    session = db()
    user = _user(session)

    first = repo.create_pending_action(
        session, user.id, "mcp__remote__delete_all", {"book": "全部"}
    )
    second = repo.create_pending_action(
        session, user.id, "mcp__remote__delete_all", {"book": "全部"}
    )

    assert first.id == second.id
    assert len(repo.list_pending_actions(session, user.id)) == 1
    # 参数不同则是另一条动作，不能被错误合并
    repo.create_pending_action(
        session, user.id, "mcp__remote__delete_all", {"book": "部分"}
    )
    assert len(repo.list_pending_actions(session, user.id)) == 2


def test_token_replay_executes_once_for_same_tool_and_args(db, loop_env):
    """确认后的令牌重放：同工具同参数执行一次，第二次被拒；工具真的只跑一次。"""
    mod, fake_rag, fake_tools = loop_env
    session = db()
    user = _user(session)
    action = repo.create_pending_action(
        session, user.id, "mcp__remote__delete_all", {"book": "全部"}
    )
    _, token = _approve(session, user.id, action.id)

    executed = []
    fake_tools.call = lambda name, **kw: (
        executed.append((name, kw)) or {"ok": True, "result": {"deleted": 1}}
    )

    def approve(name, args):
        return repo.consume_grant(session, user.id, token, name, args)

    def run_once():
        fake_rag._chat_message = FakeAPI([
            {"content": "", "tool_calls": [
                _tool_call("c1", "mcp__remote__delete_all", {"book": "全部"}),
            ]},
            {"content": '{"thought": "完成"}'},
        ])
        return mod.run(
            [{"role": "user", "content": "删掉全部"}],
            max_calls=3,
            schemas=[{"type": "function"}],
            approve=approve,
        )

    run_once()
    assert executed == [("mcp__remote__delete_all", {"book": "全部"})]

    # 第二次重放同一个令牌：工具不再执行，observation 回到 requires_confirmation
    _content, messages, _used = run_once()
    assert executed == [("mcp__remote__delete_all", {"book": "全部"})]
    denied = json.loads(messages[-1]["content"])
    assert denied["requires_confirmation"] is True


def test_token_is_bound_to_approved_arguments(db):
    """令牌只对确认时那一组参数有效；换参数拒绝，且不会把令牌消耗掉。"""
    session = db()
    user = _user(session)
    action = repo.create_pending_action(
        session, user.id, "mcp__remote__delete_all", {"book": "全部"}
    )
    _, token = _approve(session, user.id, action.id)

    assert repo.consume_grant(
        session, user.id, token, "mcp__remote__delete_all", {"book": "部分"}
    ) is False
    session.refresh(action)
    assert action.status == "approved"  # 错误参数不应消耗令牌

    assert repo.consume_grant(
        session, user.id, token, "mcp__remote__delete_all", {"book": "全部"}
    ) is True


def test_expired_token_is_rejected(db):
    """过期令牌即使参数完全一致也不能重放。"""
    session = db()
    user = _user(session)
    action = repo.create_pending_action(
        session, user.id, "mcp__remote__delete_all", {"book": "全部"}
    )
    _, token = _approve(session, user.id, action.id, ttl_seconds=-1)

    assert repo.consume_grant(
        session, user.id, token, "mcp__remote__delete_all", {"book": "全部"}
    ) is False


def test_expired_approval_can_be_reissued(db):
    """令牌过期但动作没被执行：允许重新确认，旧令牌作废，新令牌可用。"""
    session = db()
    user = _user(session)
    action = repo.create_pending_action(
        session, user.id, "mcp__remote__delete_all", {"book": "全部"}
    )
    _, old_token = _approve(session, user.id, action.id, ttl_seconds=-1)

    renewed, new_token = _approve(session, user.id, action.id)
    assert renewed.status == "approved"
    assert new_token != old_token

    # 旧令牌在重发时已被覆盖，不能再用
    assert repo.consume_grant(
        session, user.id, old_token, "mcp__remote__delete_all", {"book": "全部"}
    ) is False
    assert repo.consume_grant(
        session, user.id, new_token, "mcp__remote__delete_all", {"book": "全部"}
    ) is True

    # 已经执行过的动作不能再确认
    with pytest.raises(repo.ActionConflict):
        repo.approve_action(session, user.id, action.id)


def test_rejected_action_cannot_be_approved_or_replayed(db):
    """用户拒绝后状态是 rejected：再确认冲突，任何令牌也无法重放。"""
    session = db()
    user = _user(session)
    action = repo.create_pending_action(
        session, user.id, "mcp__remote__delete_all", {"book": "全部"}
    )
    rejected = repo.reject_action(session, user.id, action.id)
    assert rejected.status == "rejected"

    with pytest.raises(repo.ActionConflict):
        repo.approve_action(session, user.id, action.id)

    assert repo.consume_grant(
        session, user.id, "act_never_issued", "mcp__remote__delete_all", {"book": "全部"}
    ) is False


def test_concurrent_consume_allows_only_one_winner(db):
    """两个 session 同时消费同一令牌：条件 UPDATE 只让一个 rowcount=1。"""
    setup = db()
    user = _user(setup, "u-concurrent")
    action = repo.create_pending_action(
        setup, user.id, "mcp__remote__delete_all", {"book": "全部"}
    )
    _, token = _approve(setup, user.id, action.id)
    user_id = user.id

    first, second = db(), db()
    try:
        wins = [
            repo.consume_grant(
                first, user_id, token, "mcp__remote__delete_all", {"book": "全部"}
            ),
            repo.consume_grant(
                second, user_id, token, "mcp__remote__delete_all", {"book": "全部"}
            ),
        ]
        assert wins == [True, False]
        session = db()
        try:
            row = repo.get_pending_action(session, user_id, action.id)
            assert row.status == "consumed"
        finally:
            session.close()
    finally:
        first.close()
        second.close()


# --------------------------------------------------------------------------- #
# 接口层
# --------------------------------------------------------------------------- #
def test_denied_calls_are_persisted_once_and_excluded_from_answer(client, monkeypatch):
    """被拒调用落库为 pending，重复提议不产生重复行，也不混进最终回答文本。"""
    first = _chat_with_pending(client, monkeypatch)
    assert len(first["pending_actions"]) == 1
    action = first["pending_actions"][0]
    assert action["id"] > 0
    assert action["tool"] == "mcp__remote__delete_all"
    assert action["args"] == {"book": "全部"}
    assert "需要用户确认" not in first["answer"]

    second = _chat_with_pending(
        client, monkeypatch, conversation_id=first["conversation_id"]
    )
    assert [a["id"] for a in second["pending_actions"]] == [action["id"]]

    listed = client.get(
        "/v1/actions", headers={"X-Anonymous-Id": "anon-1"}
    ).json()
    assert [a["id"] for a in listed] == [action["id"]]
    assert listed[0]["status"] == "pending"


def test_pending_action_persist_failure_does_not_fail_answer(client, monkeypatch):
    """落库失败只跳过待确认项，已经生成的回答仍然正常返回。"""

    def boom(*args, **kwargs):
        raise RuntimeError("db is on fire")

    monkeypatch.setattr(api_conversations.repo, "create_pending_action", boom)
    body = _chat_with_pending(client, monkeypatch)
    assert body["answer"] == "测试回答 [1]"
    assert body["pending_actions"] == []


def test_action_endpoints_enforce_404_and_409(client, monkeypatch):
    """别人的动作 404；已确认的动作再确认 409 并带回当前状态。"""
    body = _chat_with_pending(client, monkeypatch, anon="alice")
    action_id = body["pending_actions"][0]["id"]
    alice = {"X-Anonymous-Id": "alice"}
    bob = {"X-Anonymous-Id": "bob"}

    assert client.get("/v1/actions", headers=bob).json() == []
    assert client.post(f"/v1/actions/{action_id}/approve", headers=bob).status_code == 404
    assert client.post(f"/v1/actions/{action_id}/reject", headers=bob).status_code == 404

    approved = client.post(f"/v1/actions/{action_id}/approve", headers=alice)
    assert approved.status_code == 200, approved.text
    assert approved.json()["token"].startswith("act_")
    assert approved.json()["expires_at"]

    again = client.post(f"/v1/actions/{action_id}/approve", headers=alice)
    assert again.status_code == 409
    assert again.json()["detail"]["current"]["status"] == "approved"

    # 确认后就不再是待确认项
    assert client.get("/v1/actions", headers=alice).json() == []


def test_chat_passes_one_time_approval_callback_to_agent(client, monkeypatch):
    """approvals 里的令牌被解析成回调；同一次运行只能放行一次。"""
    body = _chat_with_pending(client, monkeypatch, anon="carol")
    action_id = body["pending_actions"][0]["id"]
    headers = {"X-Anonymous-Id": "carol"}
    token = client.post(
        f"/v1/actions/{action_id}/approve", headers=headers
    ).json()["token"]

    seen = []

    def fake_agent(question, max_steps=6, api_key=None, history=None, memories=None,
                   approvals=None):
        assert approvals is not None
        seen.append(approvals("mcp__remote__delete_all", {"book": "全部"}))
        seen.append(approvals("mcp__remote__delete_all", {"book": "全部"}))
        return _agent_result()

    monkeypatch.setattr(api_conversations.agent, "agent_answer", fake_agent)
    r = client.post(
        f"/v1/conversations/{body['conversation_id']}/chat",
        json={"question": "确认后执行", "mode": "agent", "approvals": [token]},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert seen == [True, False]

    # 令牌已经 consumed，换一次请求再带同一个令牌不会再次放行
    seen.clear()
    r = client.post(
        f"/v1/conversations/{body['conversation_id']}/chat",
        json={"question": "再试一次", "mode": "agent", "approvals": [token]},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert seen == [False, False]


def test_chat_stream_done_contains_pending_actions_with_id(client, monkeypatch):
    """流式路径的 done 事件也要带走落库后的待确认动作，字段与同步一致。"""

    async def fake_stream(question, max_steps=6, api_key=None, history=None,
                          memories=None, on_delta=None, on_step=None, client=None):
        on_delta("测试回答")
        return _agent_result(pending_actions=[{
            "tool": "mcp__remote__delete_all",
            "args": {"book": "全部"},
            "reason": "工具需要用户确认后执行",
        }])

    monkeypatch.setattr(api_conversations.agent, "agent_answer_stream", fake_stream)
    conv_id = _create_conv(client, "anon-stream")
    headers = {"X-Anonymous-Id": "anon-stream"}

    with client.stream(
        "POST", f"/v1/conversations/{conv_id}/chat/stream",
        json={"question": "删掉全部", "mode": "agent"}, headers=headers,
    ) as r:
        assert r.status_code == 200
        frames = _parse_sse("".join(r.iter_text()))

    done = frames[-1][1]
    assert done["pending_actions"][0]["id"] > 0
    assert done["pending_actions"][0]["args"] == {"book": "全部"}
    listed = client.get("/v1/actions", headers=headers).json()
    assert [a["id"] for a in listed] == [done["pending_actions"][0]["id"]]
