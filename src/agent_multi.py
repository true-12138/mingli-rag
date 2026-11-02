# -*- coding: utf-8 -*-
"""多 Agent 版：Supervisor + Retriever + Verifier。

单 Agent 跑 15 条任务集暴露出来的失败是同一个形状：
拿到一本书能自圆其说的答案就收尾（a04 / d01 / d02 各少一本书），
或者该走的工具根本没走（b01 不查术语表、b04 不读上下文）。

所以这里不再让一个模型同时管「规划 / 检索 / 自检」，拆成三个角色：

  Supervisor  拆任务：把问题需要的书、前置工具列成清单；超出语料范围的先标记
  Retriever   一次只干一个子任务，必须带 book= 定向检索，不许全局泛搜
  Verifier    只看证据原文，判断够不够、缺哪本书，缺就回退给 Supervisor 补检索
  最后 Supervisor 汇总成终稿

两条硬约束和单 Agent 版完全一致：
1. citations 只允许出现本次 trace 中真实返回过的 chunk_id；
2. 工具调用预算是同一个 max_steps，不比单 Agent 多一个。

代价是 LLM 调用次数翻倍（规划 / 每条检索 / 校验 / 汇总各一次），
这部分单独记在 llm_calls 里，不和 steps 混在一起。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tools
from agent import MAX_STEPS, _finalize
from rag import _chat, _parse_json

EVIDENCE_CHAR = 420          # 喂给 Verifier / 汇总的每条证据截断长度
RETRIEVER_MAX_CALLS = 2      # 单个检索子任务最多几次工具调用（先搜，必要时再翻原文）


# ---------- 基础 ----------

class Budget:
    """工具调用预算。steps 的计量单位与单 Agent 版一致：一次工具调用 = 一步。"""

    def __init__(self, total):
        self.left = int(total)
        self.used = 0

    def take(self):
        if self.left <= 0:
            return False
        self.left -= 1
        self.used += 1
        return True


def _ask_json(system, prompt, counter=None):
    """调一次模型并解析 JSON；解析失败重试一次（实测模型偶尔吐两个对象）。"""
    for _ in range(2):
        raw = _chat([
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ])
        if counter is not None:
            counter["llm_calls"] = counter.get("llm_calls", 0) + 1
        try:
            data = _parse_json(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None


def _harvest(result):
    """从工具返回值里捞出 (chunk_id, 标题, 正文) 三元组。"""
    out = []
    if not isinstance(result, dict):
        return out
    payload = result.get("result")
    if not isinstance(payload, dict):
        return out
    for h in payload.get("hits") or []:
        if isinstance(h, dict) and "chunk_id" in h:
            out.append(h)
    if "chunk_id" in payload:
        out.append(payload)
    return out


def _excerpt(text, n=EVIDENCE_CHAR):
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[:n] + "…"


def _evidence_block(evidence):
    lines = []
    for e in evidence:
        lines.append("[chunk_id={}] {}·{}\n{}".format(
            e["chunk_id"], e["book"], e.get("chapter") or "", _excerpt(e["text"])))
    return "\n\n".join(lines)


def _short(obj, n=600):
    s = json.dumps(obj, ensure_ascii=False)
    return s if len(s) <= n else s[:n] + "…"


# ---------- 三个角色 ----------

PLANNER_PROMPT = """你是古籍问答流水线的调度者。不改写问题，只拆任务。

输出 JSON：
{
  "pre": [{"action": "工具名", "args": {...}}],
  "searches": [{"book": "书名", "query": "检索词"}],
  "out_of_scope": false,
  "reason": ""
}

pre 只放确定性的前置工具，没有就给空数组：
- 问题给了出生时间 -> draw_bazi（要看星盘才用 draw_astro）
- 提到「记得有本…」「名字带…」这类模糊书名 -> list_books
- 要先查一个术语的定义 -> search_terms
- 问题直接给了四柱 -> 不排盘

searches 是必须分别查的书写范围，规则：
1. 问题点名了哪几本书，就全部列进 searches，不能少列。
2. 问题要比较两种说法、却没说书名，就列两家都有该内容的不同书。
3. 同一概念在不同书里可能异名（例如《三命通会》全篇无「七杀」，只作「偏官」），
   检索词按每本书的实际用词写，不要一个词套所有书。
4. 最多 4 条 searches。

out_of_scope 只有在问题要求的东西语料根本不可能提供时才为 true：
金融涨跌预测、现代医学诊断、语料里没有的术数门类（如奇门遁甲起局）、
现代生活问题（考研、买房、考公）。不确定就填 false。
"""

RETRIEVER_PROMPT = """你是检索员，只负责一个子任务：把指定书里与子问题相关的原文找出来。

输出 JSON，二选一：
{"thought": "为什么这么搜", "action": "search_classics", "args": {"query": "...", "book": "指定书名", "k": 8, "mode": "rrf"}}
{"thought": "已经拿到相关原文", "action": "done"}

规则：
1. book 必须填任务里给的指定书名，不许省略 book 做全库检索。
2. mode：精确术语用 bm25，口语化转述用 dense，不确定用 rrf。
3. 如果命中的片段看起来只是擦边、必须先读完整上下文才能判断，改调
   {"action": "fetch_chunk", "args": {"chunk_id": 123, "with_neighbors": true}}
4. 拿到 1~2 处直接相关的原文就 done，不要穷举。
"""

VERIFIER_PROMPT = """你是校验员。只看证据原文，判断这些证据是否足以支撑回答，并找出缺口。
你不写答案。

输出 JSON：
{
  "sufficient": true 或 false,
  "gaps": [{"book": "缺的书名", "query": "该换什么检索词"}],
  "notes": "证据实际支持到哪一步；哪些说法没有原文支撑"
}

判据：
1. 子问题里指定的每本书都必须有证据；少一本就 sufficient=false，并在 gaps 里写清是哪本。
2. 证据只是主题相近、没有正面回答问题的，不算数。
3. 如果问题超出语料范围（金融预测、现代医学、语料没有的术数门类），
   sufficient=false，notes 里写明「语料不支持该结论」，gaps 留空。
4. gaps 最多 2 条。
"""

SYNTHESIZER_PROMPT = """你是古籍问答的终稿撰写者。只能使用给定证据里的信息，不得使用常识或记忆补充。

输出 JSON：
{
  "can_answer": true 或 false,
  "answer": "回答正文",
  "citations": [chunk_id, ...],
  "refusal_reason": null 或 "为什么证据不足"
}

规则：
1. citations 只能填证据里出现过的 chunk_id，不许自己编号，不许猜。
2. 引用了多本书时，按书写明出处，例如「《渊海子平·论伤官》说……」。
3. 证据不足、或证据只沾边不正面回答，必须 can_answer=false，
   answer 固定为「语料中没有足够的依据回答这个问题。」，citations 为 []。
4. 古代概念不能套现代生活：科举/功名≠考研，田宅≠商品房，官星≠考公，财星≠工资。
5. 不预测金融行情、现代医学结果，不判断生死疾病灾祸。
6. 你自己的推断必须明确标成「推断」，不能和原文所述混在一起说。
7. 同一概念在两本书里说法冲突时，分别陈述，不要强行统一。
"""


def _plan(question, counter):
    data = _ask_json(PLANNER_PROMPT, "【问题】\n{}".format(question), counter) or {}
    pre = [p for p in (data.get("pre") or [])
           if isinstance(p, dict) and p.get("action") in tools.TOOLS]
    searches = []
    for s in (data.get("searches") or [])[:4]:
        if isinstance(s, dict) and s.get("book") and s.get("query"):
            searches.append({"book": str(s["book"]), "query": str(s["query"])})
    return {
        "pre": pre[:4],
        "searches": searches,
        "out_of_scope": bool(data.get("out_of_scope")),
        "reason": data.get("reason") or "",
    }


def _run_pre(plan, budget, trace, evidence, seen, counter):
    """执行前置的确定性工具，返回给下游看的摘要。"""
    notes = []
    for p in plan["pre"]:
        if not budget.take():
            break
        result = tools.call(p["action"], **(p.get("args") or {}))
        got = [h["chunk_id"] for h in _harvest(result)]
        seen.update(got)
        for h in _harvest(result):
            evidence.setdefault(h["chunk_id"], {
                "chunk_id": h["chunk_id"], "book": h.get("book") or "",
                "chapter": h.get("chapter") or "", "text": h.get("text") or "",
            })
        trace.append({
            "step": len(trace) + 1, "agent": "supervisor(pre)",
            "thought": "前置工具", "action": p["action"], "args": p.get("args"),
            "ok": result.get("ok"), "chunk_ids": got, "error": result.get("error"),
        })
        if result.get("ok"):
            notes.append("{} -> {}".format(p["action"], _short(result.get("result"), 500)))
        else:
            notes.append("{} 调用失败：{}".format(p["action"], result.get("error")))
    return "\n".join(notes)


def _retrieve(task, context, budget, trace, evidence, seen, counter):
    """一个子任务：在指定书内检索，必要时翻原文。返回最后一次的 thought 供记录。"""
    messages = [
        {"role": "system", "content": RETRIEVER_PROMPT},
        {"role": "user", "content": "【子任务】在《{}》里检索：{}\n【前置结果】\n{}".format(
            task["book"], task["query"], context or "（无）")},
    ]
    calls = 0
    while calls < RETRIEVER_MAX_CALLS and budget.left > 0:
        raw = _chat(messages)
        counter["llm_calls"] = counter.get("llm_calls", 0) + 1
        try:
            data = _parse_json(raw)
        except json.JSONDecodeError:
            data = None
        if not isinstance(data, dict):
            messages.append({"role": "assistant", "content": raw[:300]})
            messages.append({"role": "user", "content": "observation: 输出不是合法 JSON，请重新只输出一个 JSON。"})
            continue

        action = data.get("action")
        if action == "done":
            return data.get("thought") or ""

        args = data.get("args") or {}
        # 检索类动作强制带上指定书名，防止退化成全库泛搜
        if action == "search_classics":
            args["book"] = task["book"]
        if not budget.take():
            return "预算用尽"

        result = tools.call(action or "", **args)
        got = [h["chunk_id"] for h in _harvest(result)]
        seen.update(got)
        for h in _harvest(result):
            evidence.setdefault(h["chunk_id"], {
                "chunk_id": h["chunk_id"], "book": h.get("book") or "",
                "chapter": h.get("chapter") or "", "text": h.get("text") or "",
            })
        trace.append({
            "step": len(trace) + 1, "agent": "retriever",
            "thought": data.get("thought"), "action": action, "args": args,
            "ok": result.get("ok"), "chunk_ids": got, "error": result.get("error"),
        })
        messages.append({"role": "assistant", "content": json.dumps(data, ensure_ascii=False)})
        messages.append({"role": "user", "content": "observation: " + _short(result, 1600)})
        calls += 1
    return "检索未收口"


def _verify(question, evidence, out_of_scope, counter):
    block = _evidence_block(evidence) or "（无证据）"
    data = _ask_json(
        VERIFIER_PROMPT,
        "【问题】\n{}\n\n【是否已判定超出语料范围】{}\n\n【证据】\n{}".format(
            question, "是" if out_of_scope else "否", block),
        counter,
    ) or {"sufficient": False, "gaps": [], "notes": "校验员未返回合法 JSON"}
    gaps = []
    for g in (data.get("gaps") or [])[:2]:
        if isinstance(g, dict) and g.get("book") and g.get("query"):
            gaps.append({"book": str(g["book"]), "query": str(g["query"])})
    return {
        "sufficient": bool(data.get("sufficient")),
        "gaps": gaps,
        "notes": data.get("notes") or "",
    }


def _synthesize(question, evidence, verdict, out_of_scope, counter):
    block = _evidence_block(evidence) or "（无证据）"
    return _ask_json(
        SYNTHESIZER_PROMPT,
        "【问题】\n{}\n\n【是否超出语料范围】{}\n\n【校验意见】\n{}{}\n\n【证据】\n{}".format(
            question,
            "是（必须拒答）" if out_of_scope else "否",
            verdict.get("notes") or "",
            "\n校验员指出证据不足，缺口：" + json.dumps(verdict.get("gaps"), ensure_ascii=False)
            if not verdict.get("sufficient") else "",
            block,
        ),
        counter,
    ) or {"can_answer": False, "answer": "", "citations": [],
          "refusal_reason": "汇总阶段未返回合法 JSON"}


# ---------- 入口 ----------

def agent_answer(question, max_steps=MAX_STEPS):
    """返回结构与 agent.agent_answer() 完全一致，另带 llm_calls / plan。"""
    counter = {"llm_calls": 0}
    budget = Budget(max_steps)
    trace = []
    evidence = {}
    seen = set()

    plan = _plan(question, counter)
    context = _run_pre(plan, budget, trace, evidence, seen, counter)

    for task in plan["searches"]:
        if budget.left <= 0:
            break
        _retrieve(task, context, budget, trace, evidence, seen, counter)

    verdict = _verify(question, list(evidence.values()), plan["out_of_scope"], counter)

    # 缺口回补：只补校验员明确点名、且预算还够的一到两本
    for gap in verdict["gaps"]:
        if budget.left <= 0:
            break
        _retrieve(gap, context, budget, trace, evidence, seen, counter)
    if verdict["gaps"] and budget.used < max_steps:
        verdict = _verify(question, list(evidence.values()), plan["out_of_scope"], counter)

    data = _synthesize(question, list(evidence.values()), verdict,
                       plan["out_of_scope"], counter)
    res = _finalize(data, seen, trace)
    res["llm_calls"] = counter["llm_calls"]
    res["plan"] = plan
    res["verdict"] = verdict
    return res


if __name__ == "__main__":
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    q = " ".join(sys.argv[1:]) or "《三命通会》和《渊海子平》对正官的解释有什么不同？"
    res = agent_answer(q)
    print("Q:", q)
    print("plan:", json.dumps(res["plan"], ensure_ascii=False))
    for t in res["trace"]:
        print("  step %s  %-14s %-26s %s  -> %s" % (
            t.get("step"), t.get("agent"), t.get("action"),
            (t.get("thought") or "")[:30], t.get("chunk_ids")))
    print("verdict:", json.dumps(res["verdict"], ensure_ascii=False))
    print("can_answer:", res["can_answer"], "| llm_calls:", res["llm_calls"],
          "| steps:", res["steps"])
    print("answer:", (res["answer"] or "")[:400])
    print("citations:", res["citations_chunk_ids"], "invalid:", res["invalid_citations"])
