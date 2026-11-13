# -*- coding: utf-8 -*-
"""长期记忆：会话摘要 + 用户偏好/事实。

边界（和 conversation.py 一致，但更严格）：

1. 记忆只用于个性化，**不作为回答证据**；引用仍只能来自本轮工具返回的 chunk。
2. 只抽用户明确说过的内容，不从助手回答里推断；一次最多 3 条。
3. 敏感信息（身份证、手机号、银行卡、密码、病史）直接丢弃，不写库。
4. 抽取/摘要失败一律返回空，不影响本轮回答——记忆是增强，不是主链路。

为什么摘要和记忆分开：
- 会话摘要属于一次对话，历史太长时替代早期消息；
- 用户记忆跨会话，按 (user_id, kind, key) 去重。

写入边界在 repo 层：首次写入直接生效；覆盖已有值会变成「待确认」，
等用户在记忆页点确认。模型听错一句话不会当场改掉用户设定好的偏好。
"""
from __future__ import annotations

import re

from db import repo

MAX_MEMORIES_PER_TURN = 3
# 存储上限和 prompt 上限是两回事：库里能放长偏好，进 prompt 时再压缩。
# 以前写入就砍到 200 字符，用户说一句带条件的偏好，后半句直接丢了，
# 而且库里再也找不回来。现在写满 2000，prompt 侧仍只带前 200 字符。
MAX_VALUE_CHARS = 2000
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,49}$")
SENSITIVE_RE = re.compile(
    r"(\b\d{17}[\dXx]\b|\b1[3-9]\d{9}\b|身份证|银行卡|密码|病史|病历)"
)

EXTRACT_PROMPT = """你是长期记忆抽取器。只从用户**明确说过**的话里抽取稳定的偏好或事实，不要从助手回答里推断。

输出 JSON：
{"memories": [{"kind": "preference", "key": "snake_case_key", "value": "中文值"}]}

规则：
1. 最多 3 条；没有就输出 {"memories": []}。
2. kind 只能是 preference（偏好）或 fact（事实）。
3. key 用英文 snake_case，不超过 50 字符；value 不超过 2000 字符，但越短越好。
4. 不要存敏感信息：身份证、手机号、住址、银行卡、密码、病史、政治宗教观点。
5. 不要存一次性的问题、助手给出的结论、推测出来的性格或命运。
6. 偏好示例：以后优先查某本书、回答要简短、只看原文。
   事实示例：出生时间、性别、常驻城市、正在研究的术语。

只输出 JSON，不要输出 JSON 以外的任何文字。
"""

SUMMARY_PROMPT = """你是会话摘要器。把早期的对话压缩成一段不超过 300 字的中文摘要。

必须保留：
1. 用户明确说过的偏好、出生信息、限定条件；
2. 已经查证过的书名/术语（只作为“聊过什么”，不要写成引用）；
3. 还没解决的问题。

不要做命理推断，不要补充对话里没有的事实，不要输出引用编号。
只输出 JSON：{"summary": "摘要正文"}
"""


def should_extract(question: str) -> bool:
    """关键词闸门：不是每轮都值得多花一次模型调用。"""
    q = question or ""
    triggers = ("记住", "以后", "偏好", "我习惯", "我的出生", "我是", "只用", "只查", "不要用")
    return any(t in q for t in triggers)


def _valid_item(item: dict) -> dict | None:
    if not isinstance(item, dict):
        return None
    kind = str(item.get("kind") or "").strip()
    key = str(item.get("key") or "").strip()
    value = str(item.get("value") or "").strip()
    if kind not in repo.MEMORY_KINDS:
        return None
    if not KEY_RE.match(key):
        return None
    if not value or len(value) > MAX_VALUE_CHARS:
        return None
    if SENSITIVE_RE.search(value):
        return None
    return {"kind": kind, "key": key, "value": value, "confidence": 0.6}


def extract_memories(question: str, answer: str, api_key=None, counter=None) -> list[dict]:
    """从一轮问答里抽记忆；任何失败都返回 []。"""
    if not question:
        return []
    from rag import _chat, _parse_json

    if counter is not None:
        counter["llm_calls"] = counter.get("llm_calls", 0) + 1
    user = "【用户】\n{}\n\n【助手】\n{}".format(
        str(question)[:500], str(answer or "")[:800]
    )
    try:
        raw = _chat(
            [
                {"role": "system", "content": EXTRACT_PROMPT},
                {"role": "user", "content": user},
            ],
            api_key=api_key,
        )
        data = _parse_json(raw)
    except Exception:
        return []
    if not isinstance(data, dict):
        return []

    out, seen = [], set()
    for item in data.get("memories") or []:
        valid = _valid_item(item)
        if valid is None:
            continue
        ident = (valid["kind"], valid["key"])
        if ident in seen:
            continue
        seen.add(ident)
        out.append(valid)
        if len(out) >= MAX_MEMORIES_PER_TURN:
            break
    return out


def summarize_messages(messages, previous: str | None = None, api_key=None) -> str | None:
    """把一批消息压成摘要；保留上次摘要作为上下文，避免越摘越窄。"""
    if not messages:
        return None
    from rag import _chat, _parse_json

    lines = []
    for m in messages:
        role = "用户" if getattr(m, "role", None) == "user" else "助手"
        lines.append("{}：{}".format(role, str(getattr(m, "content", "") or "")[:400]))
    body = "\n".join(lines)[:4000]
    prompt = ("【已有摘要】\n{}\n\n【新增对话】\n{}".format(previous, body)
              if previous else body)
    try:
        raw = _chat(
            [
                {"role": "system", "content": SUMMARY_PROMPT},
                {"role": "user", "content": prompt},
            ],
            api_key=api_key,
        )
        data = _parse_json(raw)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    summary = str(data.get("summary") or "").strip()
    return summary[:1000] or None


def maybe_summarize(session, conversation, api_key=None,
                    min_new_messages: int = 8, keep_recent: int = 4) -> str | None:
    """新消息够多时生成/更新会话摘要，并把覆盖位置写回 conversations。

    只把「最近 keep_recent 条之前」的消息送进摘要；最近几轮仍以原文进 prompt。
    """
    msgs = repo.list_messages(
        session, conversation.id, after_id=conversation.summary_upto_id or 0, limit=40
    )
    if len(msgs) < min_new_messages:
        return None
    older = msgs[:-keep_recent]
    if not older:
        return None
    summary = summarize_messages(older, previous=conversation.summary, api_key=api_key)
    if not summary:
        return None
    repo.mark_summary(session, conversation, summary, older[-1].id)
    return summary


def remember_from_turn(session, user_id: int, conversation_id: str,
                       question: str, answer: str, api_key=None,
                       counter=None) -> list:
    """抽取并合并本轮记忆；返回写入的 UserMemory 列表。"""
    if not should_extract(question):
        return []
    items = extract_memories(question, answer, api_key=api_key, counter=counter)
    saved = []
    for item in items:
        memory = repo.upsert_memory(
            session, user_id, item["kind"], item["key"], item["value"],
            source_conversation_id=conversation_id,
            confidence=item.get("confidence", 0.5),
            commit=False,
        )
        if memory is not None:
            saved.append(memory)
    if saved:
        session.commit()
    return saved
