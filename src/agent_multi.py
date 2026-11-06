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
from conversation import history_block, memory_block, normalize_history, rewrite_question

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


def _ask_json(system, prompt, counter=None, api_key=None):
    """调一次模型并解析 JSON；解析失败重试一次（实测模型偶尔吐两个对象）。"""
    for _ in range(2):
        raw = _chat([
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ], api_key=api_key)
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

_BOOK_CATALOG = None


def _book_catalog():
    """书目清单。直接调工具层，不占预算、不进 trace——它只是调度者的背景知识。"""
    global _BOOK_CATALOG
    if _BOOK_CATALOG is None:
        r = tools.call("list_books")  # 走统一入口，工具改名/加参数时这里不用跟着改
        books = (r.get("result") or {}).get("books") or []
        _BOOK_CATALOG = "、".join(b["book"] for b in books) or "（书目读取失败）"
    return _BOOK_CATALOG


PLANNER_PROMPT = """你是古籍问答流水线的调度者。只拆任务，不改写问题，不写答案。

可用工具的准确签名（参数名必须一致，写错会直接调用失败）：
- draw_bazi(year, month, day, hour=0, minute=0, gender="male")   gender 只能是 "male" 或 "female"
- draw_astro(year, month, day, hour=0, minute=0, tz=8.0, lat=39.90, lon=116.40, city="北京")
- list_books()
- search_terms(term, limit=5)

输出 JSON：
{
  "pre": [{"action": "工具名", "args": {...}}],
  "searches": [{"book": "书名", "query": "检索词"}],
  "out_of_scope": false,
  "reason": ""
}

pre 放确定性的前置工具，没有就给空数组：
1. 问题给了公历出生时间（年月日，可能带时辰、性别）-> draw_bazi；提到「星盘」「命主星」-> draw_astro。
   时间要拆成 year/month/day/hour/minute 五个参数，不要写成 birth 字符串；性别写 male/female。
2. 问题说「记得有本书…」「名字里带…」这类模糊书名 -> list_books。
3. 要先解释某个术语的定义（纳音、羊刃、咸池…）-> search_terms。
4. 问题直接给了四柱 -> 不排盘。

searches 是必须分别去查的书，规则：
1. 问题点名了哪几本书，就全部列进去，不能少列。
2. 没点名时，只从【语料书目】里挑真实存在、且确实有该内容的书，最多 3 本。
   书目里没有的书一律不许出现在 searches 里——那只会白白浪费预算。
3. 同一概念在不同书里可能异名（例如《三命通会》全篇无「七杀」，只作「偏官」），
   检索词按每本书的实际用词写，不要一个词套所有书。
4. out_of_scope 为 true 时也要列 1~2 条 searches，用来确认语料里究竟有没有相关内容，不要留空。

out_of_scope 只有在问题要求的东西语料根本不可能提供时才为 true：
金融涨跌预测、现代医学诊断、语料里没有的术数门类（如奇门遁甲起局）、
现代生活问题（考研、买房、考公）。此时 pre 里加 list_books 确认书目。
不确定就填 false。
"""

RETRIEVER_PROMPT = """你是检索员，只负责一个子任务：把指定书里与子问题相关的原文找出来。

输出 JSON，二选一：
{"thought": "为什么这么搜", "action": "search_classics", "args": {"query": "...", "k": 8, "mode": "rrf"}}
{"thought": "已经拿到能回答的原文", "action": "done"}

规则：
1. book 由系统填入任务指定的书名，你不用写，也不许改成别的书或做全库检索。
2. mode：精确术语用 bm25，口语化转述用 dense，不确定用 rrf。
3. 一次检索拿到 3 条以上相关原文就 done，不要换个 mode 再搜一遍同样的词。
4. 如果命中的片段只有结论（断语、条款、口诀），却没有前提条件，
   必须调 {"action": "fetch_chunk", "args": {"chunk_id": 123, "with_neighbors": true}}
   读完整上下文再 done。
"""

VERIFIER_PROMPT = """你是校验员。只判断材料够不够支撑回答，不写答案。

材料有两类，都算证据：
- 前置工具的确定性输出（排盘四柱、星盘、书目、术语表条目）
- 古籍原文片段

输出 JSON：
{
  "sufficient": true 或 false,
  "gaps": [...],
  "notes": "材料实际支持到哪一步；哪些说法没有依据"
}

gaps 里每一项二选一：
{"action": "search_classics", "book": "书名", "query": "检索词"}
{"action": "fetch_chunk", "chunk_id": 123}

判据：
1. 问题点名的每本书都要有原文证据；少一本就 sufficient=false，并写进 gaps。
2. 前置工具的输出本身就是证据。不要因为「古籍原文里没有排盘过程」判证据不足——
   四柱是工具算出来的事实，不是该去古籍里找的东西。
3. 古籍之间说法不一致时，只要分歧本身有原文支撑，就算 sufficient=true：
   回答完全可以陈述「甲书这样说、乙书那样说」。
4. 证据只有结论、没有前提条件时，用 fetch_chunk 的 gap 让检索员读上下文。
5. out_of_scope=true 时 sufficient=false，notes 写明「语料不支持该结论」，gaps 留空。
6. gaps 最多 2 条。
"""

SYNTHESIZER_PROMPT = """你是古籍问答的终稿撰写者。只能使用给定材料里的信息，不得使用常识或记忆补充。

输出 JSON：
{
  "can_answer": true 或 false,
  "answer": "回答正文",
  "citations": [chunk_id, ...],
  "refusal_reason": null 或 "为什么证据不足"
}

规则：
1. citations 只能填古籍证据里出现过的 chunk_id，不许自己编号，不许猜。
2. 引用了多本书时，按书写明出处，例如「《渊海子平·论伤官》说……」。
3. 前置工具输出的四柱、行星度数、命主星是已经算好的事实：直接引用，不许重算、
   不许补充盘里没有的星体或神煞。
4. 材料不足、或材料只沾边不正面回答，必须 can_answer=false，
   answer 固定为「语料中没有足够的依据回答这个问题。」，citations 为 []。
5. 古代概念不能套现代生活：科举/功名≠考研，田宅≠商品房，官星≠考公，财星≠工资。
6. 不预测金融行情、现代医学结果，不判断生死疾病灾祸。
7. 你自己的推断必须明确标成「推断」，不能和原文所述混在一起说。
8. 不同书说法冲突时分别陈述，不要强行统一。
"""


def _plan(question, counter, feedback="", api_key=None, history=""):
    prompt = (history + chr(10) + chr(10) if history else "") + "【语料书目】\n{}\n\n【问题】\n{}".format(_book_catalog(), question)
    if feedback:
        prompt += "\n\n【上一次前置工具调用失败，请按准确签名重写】\n" + feedback
    data = _ask_json(PLANNER_PROMPT, prompt, counter, api_key=api_key) or {}
    pre = [p for p in (data.get("pre") or [])
           if isinstance(p, dict) and p.get("action") in tools.TOOLS]
    searches = []
    for s in (data.get("searches") or [])[:3]:
        if isinstance(s, dict) and s.get("book") and s.get("query"):
            searches.append({"book": str(s["book"]), "query": str(s["query"])})
    return {
        "pre": pre[:4],
        "searches": searches,
        "out_of_scope": bool(data.get("out_of_scope")),
        "reason": data.get("reason") or "",
    }


def _run_pre(plan, budget, trace, evidence, seen):
    """执行前置的确定性工具。返回 (摘要, 是否全部成功)。

    摘要必须往下传：排盘/星盘的结果是证据的一部分，校验员和汇总员都要看到，
    否则它们会以为「古籍原文里没有四柱」而判证据不足——这正是第一版的坑。
    """
    notes, ok_all = [], True
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
            notes.append("{} -> {}".format(p["action"], _short(result.get("result"), 700)))
        else:
            ok_all = False
            notes.append("{} 调用失败：{}".format(p["action"], result.get("error")))
    return "\n".join(notes), ok_all


def _retrieve(task, context, budget, trace, evidence, seen, counter, api_key=None):
    """一个子任务：在指定书内检索，必要时翻原文。返回最后一次的 thought 供记录。"""
    messages = [
        {"role": "system", "content": RETRIEVER_PROMPT},
        {"role": "user", "content": "【子任务】在《{}》里检索：{}\n【前置结果】\n{}".format(
            task["book"], task["query"], context or "（无）")},
    ]
    calls = 0
    while calls < RETRIEVER_MAX_CALLS and budget.left > 0:
        raw = _chat(messages, api_key=api_key)
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


def _verify(question, evidence, pre_notes, out_of_scope, counter, api_key=None, history=""):
    block = _evidence_block(evidence) or "（无原文证据）"
    data = _ask_json(
        VERIFIER_PROMPT,
        (history + chr(10) + chr(10) if history else "") +
        "【问题】\n{}\n\n【是否已判定超出语料范围】{}\n\n"
        "【前置工具输出（算作证据）】\n{}\n\n【古籍原文证据】\n{}".format(
            question, "是" if out_of_scope else "否", pre_notes or "（无）", block),
        counter,
        api_key=api_key,
    ) or {"sufficient": False, "gaps": [], "notes": "校验员未返回合法 JSON"}
    gaps = []
    for g in (data.get("gaps") or [])[:2]:
        if not isinstance(g, dict):
            continue
        if g.get("action") == "fetch_chunk" and g.get("chunk_id") is not None:
            gaps.append({"action": "fetch_chunk", "chunk_id": g["chunk_id"]})
        elif g.get("book") and g.get("query"):
            gaps.append({"action": "search_classics",
                         "book": str(g["book"]), "query": str(g["query"])})
    return {
        "sufficient": bool(data.get("sufficient")),
        "gaps": gaps,
        "notes": data.get("notes") or "",
    }


def _synthesize(question, evidence, pre_notes, verdict, out_of_scope, counter, api_key=None, history=""):
    block = _evidence_block(evidence) or "（无原文证据）"
    return _ask_json(
        SYNTHESIZER_PROMPT,
        (history + chr(10) + chr(10) if history else "") +
        "【问题】\n{}\n\n【是否超出语料范围】{}\n\n【前置工具输出】\n{}\n\n"
        "【校验意见】\n{}{}\n\n【古籍原文证据】\n{}".format(
            question,
            "是（必须拒答）" if out_of_scope else "否",
            pre_notes or "（无）",
            verdict.get("notes") or "",
            "\n校验员指出证据不足，缺口：" + json.dumps(verdict.get("gaps"), ensure_ascii=False)
            if not verdict.get("sufficient") else "",
            block,
        ),
        counter,
        api_key=api_key,
    ) or {"can_answer": False, "answer": "", "citations": [],
          "refusal_reason": "汇总阶段未返回合法 JSON"}


def _fetch_gap(chunk_id, budget, trace, evidence, seen):
    """按校验员点名的 chunk_id 读上下文。这一步不需要模型参与。"""
    if not budget.take():
        return
    result = tools.call("fetch_chunk", chunk_id=chunk_id, with_neighbors=True)
    got = [h["chunk_id"] for h in _harvest(result)]
    seen.update(got)
    for h in _harvest(result):
        evidence.setdefault(h["chunk_id"], {
            "chunk_id": h["chunk_id"], "book": h.get("book") or "",
            "chapter": h.get("chapter") or "", "text": h.get("text") or "",
        })
    trace.append({
        "step": len(trace) + 1, "agent": "supervisor(gap)",
        "thought": "校验员要求读上下文", "action": "fetch_chunk",
        "args": {"chunk_id": chunk_id, "with_neighbors": True},
        "ok": result.get("ok"), "chunk_ids": got, "error": result.get("error"),
    })


# ---------- 入口 ----------

def agent_answer(question, max_steps=MAX_STEPS, api_key=None, history=None, memories=None):
    """返回结构与 agent.agent_answer() 完全一致，另带 llm_calls / plan。

    api_key 用于公网访客自带 key 的场景；不传则读 DEEPSEEK_API_KEY。
    history 是多轮对话历史；memories 是长期偏好/事实。先改写成独立问题，
    再把两者作为「只用于理解、不作为证据」的上下文交给各角色。
    """
    counter = {"llm_calls": 0}
    history = normalize_history(history)
    standalone = rewrite_question(question, history, api_key=api_key, counter=counter)
    question = standalone
    hist_block = "\n\n".join(b for b in (history_block(history), memory_block(memories)) if b)
    budget = Budget(max_steps)
    trace = []
    evidence = {}
    seen = set()

    plan = _plan(question, counter, api_key=api_key, history=hist_block)
    context, ok_all = _run_pre(plan, budget, trace, evidence, seen)

    # 前置工具参数写错时，把错误回给调度者按准确签名重写一次。
    # 一次修复比让整题作废便宜得多。
    if not ok_all and plan["pre"]:
        retry = _plan(question, counter, feedback=context, api_key=api_key, history=hist_block)
        context += "\n" + _run_pre({"pre": retry["pre"]}, budget, trace, evidence, seen)[0]

    for task in plan["searches"]:
        if budget.left <= 0:
            break
        _retrieve(task, context, budget, trace, evidence, seen, counter, api_key=api_key)

    verdict = _verify(question, list(evidence.values()), context,
                      plan["out_of_scope"], counter, api_key=api_key, history=hist_block)

    # 缺口回补：补检索，或按校验员指的 chunk_id 读上下文
    for gap in verdict["gaps"]:
        if budget.left <= 0:
            break
        if gap.get("action") == "fetch_chunk":
            _fetch_gap(gap["chunk_id"], budget, trace, evidence, seen)
        else:
            _retrieve(gap, context, budget, trace, evidence, seen, counter, api_key=api_key)
    if verdict["gaps"] and budget.used < max_steps:
        verdict = _verify(question, list(evidence.values()), context,
                          plan["out_of_scope"], counter, api_key=api_key, history=hist_block)

    data = _synthesize(question, list(evidence.values()), context, verdict,
                       plan["out_of_scope"], counter, api_key=api_key, history=hist_block)
    res = _finalize(data, seen, trace)
    res["llm_calls"] = counter["llm_calls"]
    res["rewritten_question"] = standalone
    res["history_turns"] = len(history)
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
