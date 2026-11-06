# -*- coding: utf-8 -*-
"""多轮对话的上下文整理与追问改写。

三条原则：
1. 历史只用于消解指代（「那第二点呢」「这本书里怎么说」），**不作为回答证据**；
   引用仍然只能来自本轮工具实际返回的 chunk。
2. 只保留最近 MAX_TURNS 轮，并按字符预算从旧到新截断，避免上下文无限膨胀。
3. 改写失败时退回原问题：多轮是增强，不能把单轮能力拖垮。
"""

MAX_TURNS = 3
MAX_CHARS = 1200

REWRITE_PROMPT = """你是检索查询改写器。根据对话历史，把用户最后一句追问改写成不依赖上文、可以独立检索的问题。

规则：
1. 只补全指代和省略，不添加历史里没有的事实，不回答问题。
2. 保留原问题里的限定条件（书名、性别、时间、术语）。
3. 如果最后一句本身已经完整，原样返回。
4. 只输出 JSON：{"standalone": "改写后的问题"}
"""


def normalize_history(history, max_turns=MAX_TURNS, max_chars=MAX_CHARS):
    """清洗并裁剪历史，返回 [{"role": ..., "content": ...}]。

    保留最近的对话，从旧消息开始丢；单条消息过长时保留开头（通常包含主题），
    因为助手回答的结尾常是套话，开头更可能是用户追问指向的内容。
    """
    if not history:
        return []
    turns = []
    for m in history:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        content = str(m.get("content") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        turns.append({"role": role, "content": content})
    turns = turns[-(max_turns * 2):]

    kept = []
    used = 0
    for m in reversed(turns):
        if used >= max_chars:
            break
        room = max_chars - used
        text = m["content"]
        if len(text) > room:
            text = text[: max(0, room - 1)] + "…"
        kept.append({"role": m["role"], "content": text})
        used += len(text)
    return list(reversed(kept))


def history_block(history):
    """把历史拼成 prompt 里的一段。显式标注「不作为证据」，防止模型拿旧结论当引用。"""
    if not history:
        return ""
    lines = ["【对话历史（只用于理解追问，不作为回答证据）】"]
    for m in history:
        lines.append(("用户：" if m["role"] == "user" else "助手：") + m["content"])
    return "\n".join(lines)


MAX_MEMORIES = 8


def memory_block(memories):
    """把长期记忆拼成 prompt 里的一段。

    显式标注「不作为回答证据」：记忆只影响检索偏好/称呼，不能变成引用。
    支持 ORM 对象和 dict，调用方不用先转换。
    """
    if not memories:
        return ""
    lines = ["【长期记忆（用户此前明确说过的偏好/事实；只用于个性化，不作为回答证据）】"]
    for m in list(memories)[:MAX_MEMORIES]:
        if isinstance(m, dict):
            kind, key, value = m.get("kind"), m.get("key"), m.get("value")
        else:
            kind = getattr(m, "kind", "")
            key = getattr(m, "key", "")
            value = getattr(m, "value", "")
        kind_label = "偏好" if kind == "preference" else "事实"
        lines.append("- [{}] {}: {}".format(kind_label, key, str(value)[:200]))
    return "\n".join(lines)


def rewrite_question(question, history, api_key=None, counter=None):
    """把追问改写成独立检索问题。失败或不需要改写时返回原问题。"""
    history = normalize_history(history)
    if not history:
        return question

    # 延迟导入：rag 在模块顶层会 import 本模块的函数，避免循环依赖。
    from rag import _chat, _parse_json

    prompt = history_block(history) + "\n\n【最后一句追问】\n" + question
    if counter is not None:
        counter["llm_calls"] = counter.get("llm_calls", 0) + 1
    try:
        raw = _chat(
            [
                {"role": "system", "content": REWRITE_PROMPT},
                {"role": "user", "content": prompt},
            ],
            api_key=api_key,
        )
        data = _parse_json(raw)
        standalone = str((data or {}).get("standalone") or "").strip()
        # 改写结果只接受短问题；一旦模型写成一段话，直接退回原问题。
        if standalone and len(standalone) <= 200 and "\n" not in standalone:
            return standalone
    except Exception:
        # 改写只是增强：网络、额度、解析任何一步失败都退回原问题，不能拖垮单轮能力。
        pass
    return question
