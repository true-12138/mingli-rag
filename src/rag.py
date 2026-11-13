import io
import json
import os
import time
from dotenv import load_dotenv
load_dotenv()
import re
import sys
import requests
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from retrieval import retrieve_one
from conversation import history_block, memory_block, normalize_history, rewrite_question
import usage
DEEPSEEK_URL = os.environ.get("MINGLI_LLM_URL", "https://api.deepseek.com/chat/completions")
MODEL = os.environ.get("MINGLI_LLM_MODEL", "deepseek-chat")
REFUSAL_TEXT = "语料中没有足够的依据回答这个问题。"
SYSTEM_PROMPT = """你是一个只依据给定古籍片段回答问题的助手。
规则：
1. 只能使用【片段】里出现的信息，不得使用常识、预训练知识或推测补充。
2. 如果片段只是主题相近，但不能直接回答问题，必须拒答。
   特别注意：古代概念不能直接套现代生活问题。
   例如科举/功名 ≠ 考研，田宅 ≠ 商品房，驿马/迁移 ≠ 出国留学或辞职，
   官星/官贵 ≠ 考公务员，财星 ≠ 工资或买房。
3. 每个结论后面用方括号标注依据的片段编号，例如 [1]、[3]。
4. 不确定时拒答，不要勉强回答。
5. 对话历史和长期记忆只用于理解追问/个性化，不能作为回答证据；引用只能来自本轮【片段】。
6. 只输出 JSON，不要输出 JSON 以外的任何文字。
JSON 格式：
{
  "can_answer": true 或 false,
  "answer": "回答正文",
  "citations": [1, 3],
  "refusal_reason": null 或 "为什么片段不足以回答"
}
如果 can_answer 为 false：
- answer 固定为 "语料中没有足够的依据回答这个问题。"
- citations 为 []
"""
def _get_api_key(api_key=None):
    """取 key：调用方显式传入的优先，其次环境变量。

    这里抛 RuntimeError 而不是 SystemExit——Streamlit 的 `except Exception`
    接不住 SystemExit，公网没配 key 时整页会断在半路，看起来像前端坏了。
    """
    key = api_key or os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError(
            "没有找到 DEEPSEEK_API_KEY。先执行：\n"
            "  export DEEPSEEK_API_KEY=sk-xxxx\n"
            "或把 key 配到运行环境里。不要把 key 写进代码或提交到 git。"
        )
    return key
def build_context(hits):
    lines = []
    for i, h in enumerate(hits, 1):
        m = h["meta"]
        # 无标点组的 volume / chapter 全部为空，标点组也有 1500+ 条没有卷名，
        # 固定拼三个字段会渲染成《太乙金镜式经··》。只拼非空的部分。
        parts = [str(m.get(k) or "").strip() for k in ("book", "volume", "chapter")]
        title = "《{}》".format("·".join(p for p in parts if p))
        lines.append("[{}] {}\n{}".format(i, title, h["text"]))
    return "\n\n".join(lines)
def _parse_json(raw):
    raw = raw.strip()
    # 防止模型偶尔套 ```json 围栏
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # 模型偶尔一次输出两个 JSON（观察到 a03/b03 里有），整段解析会失败、
        # 白白浪费一步。退化为只取第一个对象：后面那个留给下一轮。
        obj, _end = json.JSONDecoder().raw_decode(raw)
        return obj
# 429 是限流，5xx 是服务端瞬时故障：都值得重试。400 是请求本身有问题，
# 重试只会把同一个错误再买一遍，所以原样抛出。
RETRY_STATUS = (429, 500, 502, 503, 504)
RETRY_ATTEMPTS = 3
RETRY_MAX_WAIT = 8.0


def _post_chat(body, api_key=None):
    """POST 一次 chat/completions，对 429/5xx 做有限次指数退避。

    2026-11-07 多 Agent 全量评测里出现过 7/30 条 HTTP 500，单次请求的实现
    会把整题判失败；加这层后，同样的题只会慢几秒，不会整批作废。
    """
    headers = {
        "Authorization": "Bearer {}".format(_get_api_key(api_key)),
        "Content-Type": "application/json",
    }
    resp = None
    for attempt in range(RETRY_ATTEMPTS):
        resp = requests.post(DEEPSEEK_URL, headers=headers, json=body, timeout=120)
        if resp.status_code not in RETRY_STATUS or attempt + 1 >= RETRY_ATTEMPTS:
            return resp
        raw_wait = (getattr(resp, "headers", None) or {}).get("Retry-After")
        try:
            delay = float(raw_wait)
        except (TypeError, ValueError):
            delay = 2.0 ** attempt
        time.sleep(min(delay, RETRY_MAX_WAIT))
    return resp


def _chat_message(messages, tools=None, temperature=0.0, api_key=None, tool_choice=None):
    """调一次模型，返回完整的 message 对象（而不是只取 content）。

    function calling 需要拿到 tool_calls 和每个调用的 id，所以单独开这个口子；
    不带 tools 时仍然用 response_format=json_object，行为和原来的 _chat 一致。
    """
    body = {
        "model": MODEL,
        "messages": messages,
        "temperature": temperature,
    }
    if tools:
        body["tools"] = tools
        if tool_choice:
            body["tool_choice"] = tool_choice
    else:
        body["response_format"] = {"type": "json_object"}
    resp = _post_chat(body, api_key=api_key)
    if resp.status_code >= 400:
        # 只抛状态码的话，400 分不清是 schema 不合法、JSON 模式缺关键字还是消息顺序问题。
        # 把 API 返回的原文带进异常，评测结果里才能直接看到原因。
        raise RuntimeError("DeepSeek HTTP {}：{}".format(resp.status_code, resp.text[:600]))
    payload = resp.json()
    if not isinstance(payload, dict):
        raise RuntimeError("DeepSeek 返回了空/非对象 JSON：{!r}".format(payload))
    if payload.get("error"):
        raise RuntimeError("DeepSeek 返回错误：{}".format(payload["error"]))
    # 旁路累计 token；没有 reset() 的调用方（脚本 / 测试）不记录，不影响行为
    usage.add(payload.get("usage"))
    message = payload["choices"][0]["message"]
    # tool_loop 用 usage 做单次运行的 token 预算。放回 message 不影响协议，
    # 因为它只挑 content / tool_calls 回灌给下一轮。
    used = payload.get("usage")
    if isinstance(used, dict):
        message = {**message, "usage": used}
    return message


def _chat(messages, temperature=0.0, api_key=None):
    msg = _chat_message(messages, temperature=temperature, api_key=api_key)
    return msg.get("content") or ""
def answer(question, top_k=5, mode="rrf", api_key=None, history=None, memories=None):
    """返回 dict：can_answer / answer / citations / citations_chunk_ids / ...
    can_answer=False 才算一次拒答。
    api_key 用于公网访客自带 key 的场景，不传就读环境变量。
    history 是多轮对话历史；memories 是长期偏好/事实。两者都只用于理解问题，
    不作为回答证据。
    """
    counter = {"llm_calls": 0}
    history = normalize_history(history)
    standalone = rewrite_question(question, history, api_key=api_key, counter=counter)
    hits = retrieve_one(standalone, top_k=top_k, mode=mode)
    hist = history_block(history)
    mem = memory_block(memories)
    user = (hist + "\n\n" if hist else "") + (mem + "\n\n" if mem else "") + \
        "【片段】\n{}\n\n【问题】\n{}".format(build_context(hits), standalone)
    data = None
    last_raw = ""
    for _ in range(2):  # JSON 解析失败重试一次
        last_raw = _chat(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            api_key=api_key,
        )
        counter["llm_calls"] += 1
        try:
            data = _parse_json(last_raw)
            break
        except json.JSONDecodeError:
            data = None
    if data is None:
        return {
            "can_answer": None,
            "answer": "",
            "citations": [],
            "citations_chunk_ids": [],
            "invalid_citations": [],
            "invalid_output": True,
            "error": "JSON 解析失败",
            "raw": last_raw,
            "retrieved_chunk_ids": [h["chunk_id"] for h in hits],
            "rewritten_question": standalone,
            "history_turns": len(history),
            "llm_calls": counter["llm_calls"],
        }
    return _finalize_rag(data, hits, standalone, history, counter)


def _finalize_rag(data, hits, standalone, history, counter):
    """把模型输出整理成对外结构。同步 `answer` 和异步 `answer_stream` 共用，
    保证两条路径的引用校验、拒答归一化完全一致。"""
    cited = data.get("citations") or []
    valid_nums, invalid_nums = [], []
    for n in cited:
        if isinstance(n, int) and 1 <= n <= len(hits):
            valid_nums.append(n)
        else:
            invalid_nums.append(n)
    data["citations_chunk_ids"] = [hits[n - 1]["chunk_id"] for n in valid_nums]
    # RAG 正文里的 [n] 指第 n 条召回片段，不是 chunk_id。
    # 把「标记 → chunk」显式记下来，前端点 [n] 才能落到正确的原文。
    data["citation_map"] = [
        {"marker": n, "chunk_id": hits[n - 1]["chunk_id"]} for n in valid_nums
    ]
    data["invalid_citations"] = invalid_nums
    data["retrieved_chunk_ids"] = [h["chunk_id"] for h in hits]
    # 声称能答却没有一条有效引用：不算拒答，但要标成不合规输出
    data["invalid_output"] = bool(data.get("can_answer")) and not valid_nums
    data["rewritten_question"] = standalone
    data["history_turns"] = len(history)
    data["llm_calls"] = counter["llm_calls"]
    if data.get("can_answer") is False and not data.get("answer"):
        data["answer"] = REFUSAL_TEXT
        data["citations"] = []
    return data


async def answer_stream(question, top_k=5, mode="rrf", api_key=None, history=None,
                        memories=None, on_delta=None, on_step=None, client=None):
    """RAG 模式的流式版：检索照旧，生成逐 token 下发。

    检索是同步 numpy 计算，丢线程池；生成走 `llm` 异步客户端 +
    `AnswerExtractor` 从流式 json_object 里增量解出 answer 字段。
    `on_delta` 是预览，调用方以返回值的 answer 为准（拒答归一化会改正文）。
    """
    import asyncio

    import llm
    from answer_stream import AnswerExtractor
    from conversation import arewrite_question

    client = client or llm.default_client()
    counter = {"llm_calls": 0}
    history = normalize_history(history)
    standalone = await arewrite_question(question, history, api_key=api_key,
                                         counter=counter, client=client)
    hits = await asyncio.to_thread(retrieve_one, standalone, top_k=top_k, mode=mode)
    if on_step is not None:
        on_step({
            "agent": "retrieval",
            "tool": "retrieve",
            "args": {"query": standalone, "top_k": top_k, "mode": mode},
            "ok": True,
            "chunk_ids": [h["chunk_id"] for h in hits],
            "error": None,
        })

    hist = history_block(history)
    mem = memory_block(memories)
    user = ((hist + "\n\n") if hist else "") + ((mem + "\n\n") if mem else "") + \
        "【片段】\n{}\n\n【问题】\n{}".format(build_context(hits), standalone)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]

    streamed = False
    last_raw = ""
    data = None
    for _ in range(2):  # JSON 解析失败重试一次；已下发过正文则不再重放
        use_delta = on_delta if (on_delta is not None and not streamed) else None
        extractor = AnswerExtractor()
        parts = []
        async for event in client.stream(messages, api_key=api_key,
                                         response_format={"type": "json_object"}):
            if event["type"] == "delta":
                parts.append(event["text"])
                if use_delta is not None:
                    text = extractor.feed(event["text"])
                    if text:
                        use_delta(text)
                        streamed = True
            else:
                usage = event.get("usage")
                if usage:
                    counter.setdefault("usage", []).append(usage)
        counter["llm_calls"] += 1
        last_raw = "".join(parts)
        try:
            data = _parse_json(last_raw)
            break
        except json.JSONDecodeError:
            data = None
    if data is None:
        return {
            "can_answer": None,
            "answer": "",
            "citations": [],
            "citations_chunk_ids": [],
            "invalid_citations": [],
            "invalid_output": True,
            "error": "JSON 解析失败",
            "raw": last_raw,
            "retrieved_chunk_ids": [h["chunk_id"] for h in hits],
            "rewritten_question": standalone,
            "history_turns": len(history),
            "llm_calls": counter["llm_calls"],
        }
    out = _finalize_rag(data, hits, standalone, history, counter)
    out["usage"] = llm.merge_usage(counter.get("usage"))
    return out


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    q = " ".join(sys.argv[1:]) or "算命的说我命里带羊刃，这东西还分好几种？"
    print(json.dumps(answer(q), ensure_ascii=False, indent=2))
