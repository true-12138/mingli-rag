# -*- coding: utf-8 -*-
"""带工具调用的古籍问答 Agent。

和 rag.py 的单轮流程相比，区别只有一个：**检索不再是固定的那一次**。
模型可以自己决定搜什么、搜哪本书、用哪路检索、要不要翻完整原文。

但可信度这条线不能丢，所以有两条硬约束：
1. citations 里只能出现本次 trace 中真实返回过的 chunk_id；
2. 走满 max_steps 还没收口，一律按「证据不足」拒答，不允许自由发挥。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tools
from rag import REFUSAL_TEXT, _chat, _parse_json
from conversation import history_block, normalize_history, rewrite_question
import agent_state

# 提示词与参数统一走 Agent State，评测才能把一次 run 归因到具体版本。
_CONFIG = agent_state.load_config()
MAX_STEPS = _CONFIG["max_steps"]
SYSTEM_PROMPT = agent_state.load_prompt("single_system")


def _obs(result):
    """把工具返回值压成一条 observation 消息；失败的调用也要回给模型。"""
    return "observation: " + json.dumps(result, ensure_ascii=False)


def _collect_ids(result):
    """从工具返回值里捞出所有 chunk_id，用于校验 citations。"""
    ids = []
    if not isinstance(result, dict):
        return ids
    payload = result.get("result")
    if isinstance(payload, dict):
        if "chunk_id" in payload:
            ids.append(payload["chunk_id"])
        for h in payload.get("hits") or []:
            if isinstance(h, dict) and "chunk_id" in h:
                ids.append(h["chunk_id"])
        for key in ("prev", "next"):
            nb = payload.get(key)
            if isinstance(nb, dict) and "chunk_id" in nb:
                ids.append(nb["chunk_id"])
    return ids


def _finalize(data, seen, trace):
    """把模型给出的 final 整理成和 rag.answer() 一致的返回结构。"""
    can_answer = data.get("can_answer")
    answer = (data.get("answer") or "").strip()
    raw_citations = data.get("citations") or []

    valid, invalid = [], []
    for cid in raw_citations:
        try:
            cid = int(cid)
        except (TypeError, ValueError):
            invalid.append(cid)
            continue
        if cid in seen:
            valid.append(cid)
        else:
            invalid.append(cid)

    if can_answer is False:
        return {
            "can_answer": False,
            "answer": REFUSAL_TEXT,
            "citations": [],
            "citations_chunk_ids": [],
            "invalid_citations": invalid,
            "invalid_output": False,
            "refusal_reason": data.get("refusal_reason"),
            "retrieved_chunk_ids": sorted(seen),
            "trace": trace,
            "steps": len(trace),
        }

    if not answer or not valid:
        # 声称能答却没有一条可用引用 —— 和单轮流程一样判为不合规输出
        return {
            "can_answer": None if not answer else can_answer,
            "answer": answer or REFUSAL_TEXT,
            "citations": [],
            "citations_chunk_ids": [],
            "invalid_citations": invalid,
            "invalid_output": True,
            "refusal_reason": None,
            "retrieved_chunk_ids": sorted(seen),
            "trace": trace,
            "steps": len(trace),
        }

    return {
        "can_answer": True,
        "answer": answer,
        "citations": valid,
        "citations_chunk_ids": valid,
        "invalid_citations": invalid,
        "invalid_output": bool(invalid),
        "refusal_reason": None,
        "retrieved_chunk_ids": sorted(seen),
        "trace": trace,
        "steps": len(trace),
    }


def agent_answer(question, max_steps=MAX_STEPS, api_key=None, history=None):
    """跑一次 agent 循环。返回结构与 rag.answer() 兼容，额外带 trace / steps。

    api_key 用于公网访客自带 key 的场景；不传则读 DEEPSEEK_API_KEY。
    history 是多轮对话历史；只用于改写追问，不作为回答证据。
    """
    counter = {"llm_calls": 0}
    history = normalize_history(history)
    standalone = rewrite_question(question, history, api_key=api_key, counter=counter)
    trace = []
    seen = set()
    hist = history_block(history)
    user_text = (hist + "\n\n" if hist else "") + "【问题】\n{}".format(standalone)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_text},
    ]

    for step in range(1, max_steps + 1):
        raw = _chat(messages, api_key=api_key)
        counter["llm_calls"] += 1
        try:
            data = _parse_json(raw)
        except json.JSONDecodeError:
            data = None

        if not isinstance(data, dict):
            trace.append({"step": step, "error": "输出不是 JSON", "raw": raw[:300]})
            messages.append({"role": "assistant", "content": raw})
            messages.append(
                {"role": "user", "content": "observation: 你的输出不是合法 JSON，请重新只输出一个 JSON。"}
            )
            continue

        action = data.get("action")
        if action == "final":
            out = _finalize(data, seen, trace)
            out["rewritten_question"] = standalone
            out["history_turns"] = len(history)
            out["llm_calls"] = counter["llm_calls"]
            return out

        result = tools.call(action or "", **(data.get("args") or {}))
        got = _collect_ids(result)
        seen.update(got)
        trace.append(
            {
                "step": step,
                "thought": data.get("thought"),
                "action": action,
                "args": data.get("args"),
                "ok": result.get("ok"),
                "chunk_ids": got,
                "error": result.get("error"),
            }
        )
        messages.append({"role": "assistant", "content": json.dumps(data, ensure_ascii=False)})
        messages.append({"role": "user", "content": _obs(result)})

    return {
        "can_answer": False,
        "answer": REFUSAL_TEXT,
        "citations": [],
        "citations_chunk_ids": [],
        "invalid_citations": [],
        "invalid_output": False,
        "refusal_reason": "步数用尽（%d 步）仍未得出有依据的结论" % max_steps,
        "retrieved_chunk_ids": sorted(seen),
        "trace": trace,
        "steps": len(trace),
        "rewritten_question": standalone,
        "history_turns": len(history),
        "llm_calls": counter["llm_calls"],
    }


if __name__ == "__main__":
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    q = " ".join(sys.argv[1:]) or "《三命通会》和《渊海子平》对正官的解释有什么不同？"
    res = agent_answer(q)
    print("Q:", q)
    for t in res["trace"]:
        print("  step %s  %-16s %s  -> %s" % (t.get("step"), t.get("action"), (t.get("thought") or "")[:40], t.get("chunk_ids")))
    print("can_answer:", res["can_answer"])
    print("answer:", res["answer"][:300])
    print("citations:", res["citations_chunk_ids"])
    print("invalid:", res["invalid_citations"], "steps:", res["steps"])
