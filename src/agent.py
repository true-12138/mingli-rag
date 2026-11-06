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
from conversation import history_block, memory_block, normalize_history, rewrite_question

MAX_STEPS = 6

SYSTEM_PROMPT = """你是古籍检索 Agent。你不能凭记忆回答，只能通过工具查证后再回答。

可用工具：
1. search_classics(query, k, book=None, mode="rrf")
   - mode="dense" 语义相似，适合口语化/转述的问题
   - mode="bm25" 字面匹配，适合精确术语（如「飞刃」「夹禄」）
   - mode="rrf" 两路融合，不确定时用这个（默认）
   - book 传书名片段可限定在某本书内检索
2. fetch_chunk(chunk_id, with_neighbors=False) 取某条完整原文，判断片段是否真的回答了问题
3. list_books() 列出库里所有书和 chunk 数
4. search_terms(term) 查术语表
5. draw_bazi(year, month, day, hour=0, minute=0, gender="male") 排八字盘，返回四柱/藏干/十神/五行/大运
6. draw_astro(year, month, day, hour=0, minute=0, tz=8.0, lat=39.90, lon=116.40, city="北京") 排本命星盘
7. draw_tarot(n=3, seed=None, spread=None) 抽塔罗牌，spread 可选 single/three/cross

每一步只输出一个 JSON，两种格式二选一：
{"thought": "为什么这么做", "action": "工具名", "args": {...}}
{"thought": "证据够了", "action": "final", "can_answer": true, "answer": "回答正文", "citations": [chunk_id, ...], "refusal_reason": null}

规则：
1. citations 只能填工具**实际返回过**的 chunk_id，不能自己编号、不能猜。
2. 需要对比两本书时，分别对每本书调 search_classics(book="书名")。
3. 片段只是主题相近但不能直接回答问题，必须 can_answer=false。
4. 古代概念不能套现代生活：科举/功名≠考研，田宅≠商品房，官星≠考公，财星≠工资。
5. 最多 6 步，超出会被强制按「证据不足」处理。
6. 排盘工具返回的干支、行星度数、牌面是**已经算好的事实**：可以解释，不许重算、不许补充盘里没有的星体或神煞。
7. 同一个出生时间只调一次排盘工具，不要反复调用；解读用倾向性语言，不做生死/疾病/灾祸/婚姻成败的断言。
8. 对话历史和长期记忆只用于理解追问/个性化，不能作为回答证据；citations 只能来自本次工具实际返回过的 chunk_id。
9. 检索词用术语本身（2–8 字），不要把整句问题塞进 query；同一个概念的古称可能不同（如七杀/偏官、羊刃/阳刃、空亡/旬空），某个词 0 命中或结果明显不相关时，换同义词、别名或缩短检索词再试一次。
10. 命中的是目录/篇名（如「三十一．论正官」）却没有正文时，用 fetch_chunk(chunk_id, with_neighbors=true) 取相邻正文，不要只凭目录片段下结论。
"""


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

    tool_fact = any(
        t.get("action") in ("draw_bazi", "draw_astro", "draw_tarot")
        and t.get("ok") is not False
        for t in (trace or [])
    )
    if not answer or not valid:
        if answer and tool_fact:
            # 排盘/抽牌是确定性工具输出，回答可以不带 chunk 引用。
            return {
                "can_answer": True,
                "answer": answer,
                "citations": [],
                "citations_chunk_ids": [],
                "invalid_citations": invalid,
                "invalid_output": bool(invalid),
                "refusal_reason": None,
                "retrieved_chunk_ids": sorted(seen),
                "trace": trace,
                "steps": len(trace),
            }
        # 声称能答却没有引用，也没有确定性工具支撑 → 归一化为拒答。
        return {
            "can_answer": False,
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


def agent_answer(question, max_steps=MAX_STEPS, api_key=None, history=None, memories=None):
    """跑一次 agent 循环。返回结构与 rag.answer() 兼容，额外带 trace / steps。

    api_key 用于公网访客自带 key 的场景；不传则读 DEEPSEEK_API_KEY。
    history 是多轮对话历史；memories 是长期偏好/事实。两者都只用于理解问题，
    不作为回答证据。
    """
    counter = {"llm_calls": 0}
    history = normalize_history(history)
    standalone = rewrite_question(question, history, api_key=api_key, counter=counter)
    trace = []
    seen = set()
    hist = history_block(history)
    mem = memory_block(memories)
    user_text = (hist + "\n\n" if hist else "") + (mem + "\n\n" if mem else "") + \
        "【问题】\n{}".format(standalone)
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
