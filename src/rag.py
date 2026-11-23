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
import router
import usage
DEEPSEEK_URL = os.environ.get("MINGLI_LLM_URL", "https://api.deepseek.com/chat/completions")
MODEL = os.environ.get("MINGLI_LLM_MODEL", "deepseek-chat")
REFUSAL_TEXT = "语料中没有足够的依据回答这个问题。"
SYSTEM_PROMPT = """你是一个只依据给定古籍片段回答问题的助手。
规则：
1. 只能使用【片段】里出现的信息，不得使用常识、预训练知识或推测补充。
2. 判断分两步：先看**对象**，再看**属性**。
   - 片段完全没谈到问题问的对象（只是同音近形、或泛泛主题相近）：拒答。
   - 片段谈到了对象，只是原文没有「定义」「即」「所谓」这类句式：**不算证据不足**。
     按原文实际说到的内容回答，并说明原文支持到哪一步。
   - 问「是什么 / 定义 / 含义」时，片段里对它的义理、作用、分类、取舍都属于答案；
     不许以「没有形式化定义」为由拒答。
   - 问的是清单类属性（宜忌、起法、分类、用法），原文只列了一部分：答出有的部分，
     其余直接写「片段中没有」。
3. 古代概念不能直接套现代生活问题——这类类比不属于「有证据」，仍然拒答。
   例如科举/功名 ≠ 考研，田宅 ≠ 商品房，驿马/迁移 ≠ 出国留学或辞职，
   官星/官贵 ≠ 考公务员，财星 ≠ 工资或买房。
   用户拿命理结论替自己做**现实决定**（买不买 / 投不投 / 加不加杠杆、怎么治病、要不要起诉、
   婚姻成败、能不能录取）时：整题拒答，can_answer=false、citations=[]，只回固定拒答句，
   不追加任何理论讲解——讲理论也是在给判断框架。
4. 每个结论后面用方括号标注依据的片段编号，例如 [1]、[3]。
5. 不确定时拒答，不要勉强回答。但「不确定」指的是原文不支持，
   不是指原文的表述方式不够标准、不够完整。
6. 对话历史和长期记忆只用于理解追问/个性化，不能作为回答证据；引用只能来自本轮【片段】。
7. 只输出 JSON，不要输出 JSON 以外的任何文字。
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
- refusal_reason 必须写明缺的是哪一环：对象没出现 / 对象有但问的属性没出现 /
  只有现代生活的类比而没有古代原文
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


def _chat_message(messages, tools=None, temperature=0.0, api_key=None, tool_choice=None,
                  model=None, thinking=None, reasoning_effort=None):
    """调一次模型，返回完整的 message 对象（而不是只取 content）。

    function calling 需要拿到 tool_calls 和每个调用的 id，所以单独开这个口子；
    不带 tools 时仍然用 response_format=json_object，行为和原来的 _chat 一致。
    model / thinking / reasoning_effort 由 router 按题目的难度传入；不传时
    沿用原来的全局 MODEL，老调用方的行为不变。
    """
    body = {
        "model": model or MODEL,
        "messages": messages,
        "temperature": temperature,
    }
    if thinking in ("enabled", "disabled"):
        body["thinking"] = {"type": thinking}
        if thinking == "enabled" and reasoning_effort:
            body["reasoning_effort"] = reasoning_effort
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


def _chat(messages, temperature=0.0, api_key=None, model=None, thinking=None,
          reasoning_effort=None):
    msg = _chat_message(
        messages,
        temperature=temperature,
        api_key=api_key,
        model=model,
        thinking=thinking,
        reasoning_effort=reasoning_effort,
    )
    return msg.get("content") or ""


def _usage_delta(before, after):
    """两次 usage.snapshot 的差值：用来把 token 账单归到具体哪个档位。

    调用方没有 reset 时也能算对；after 为空（脚本 / 测试没开采集）则返回 None。
    """
    if not after:
        return None
    before = before or {}
    keys = ("prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens",
            "llm_calls")
    return {k: int(after.get(k, 0) or 0) - int(before.get(k, 0) or 0) for k in keys}


def _rag_messages(hits, user, chart):
    import chart_context

    return [
        {"role": "system", "content": chart_context.system_prompt(SYSTEM_PROMPT, chart)},
        {"role": "user", "content": user},
    ]


def _generate_rag(messages, api_key, spec, counter):
    """用指定档位的模型生成并解析，最多试两次 JSON。"""
    data = None
    last_raw = ""
    before = usage.snapshot()
    for _ in range(2):  # JSON 解析失败重试一次
        last_raw = _chat(
            messages,
            api_key=api_key,
            model=spec.model,
            **spec.request_fields(),
        )
        counter["llm_calls"] += 1
        try:
            data = _parse_json(last_raw)
            break
        except json.JSONDecodeError:
            data = None
    return data, last_raw, _usage_delta(before, usage.snapshot())


def _failure_rag(hits, standalone, history, counter, last_raw):
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


def _attach_route(out, route, attempts, escalated=False, escalation_reason=""):
    info = route.as_dict()
    final = attempts[-1] if attempts else None
    if final:
        info["tier"] = final["tier"]
        info["model"] = final["model"]
        info["thinking"] = final.get("thinking")
        info["effort"] = final.get("effort")
    info["escalated"] = escalated
    info["attempts"] = attempts
    if escalated:
        info["escalation_reason"] = escalation_reason
        info["reason"] = "{}；{}".format(route.reason, escalation_reason)
    out["route"] = info
    return out


def _skip_retrieval(chart):
    """姓名盘不检索古籍：答案来自盘面查表，检索只会引入噪声和超时。"""
    return bool(chart) and chart.get("kind") == "name"


def answer(question, top_k=5, mode="rrf", api_key=None, history=None, memories=None,
           chart=None, tier="auto"):
    """返回 dict：can_answer / answer / citations / citations_chunk_ids / ...
    can_answer=False 才算一次拒答。
    api_key 用于公网访客自带 key 的场景，不传就读环境变量。
    history 是多轮对话历史；memories 是长期偏好/事实。两者都只用于理解问题，
    不作为回答证据。
    chart 是用户在排盘页算好的盘面；它进 prompt 但也**不是**引用依据。
    tier 是请求级档位：auto（按难度路由）/ small / large。
    """
    import chart_context

    counter = {"llm_calls": 0}
    history = normalize_history(history)
    standalone = rewrite_question(question, history, api_key=api_key, counter=counter)
    route = router.decide(standalone, history=history, chart=chart, tier=tier, mode="rag")
    if _skip_retrieval(chart):
        # 姓名盘的答案来自五格查表，不靠古籍；不检索既避开 embed 抖动，
        # 也避免模型拿五行古籍去套 1928 年的数理体系。
        search_query, hits = "", []
    else:
        search_query = chart_context.retrieval_query(chart, standalone)
        hits = retrieve_one(search_query, top_k=top_k, mode=mode)
    hist = history_block(history)
    mem = memory_block(memories)
    ctx = chart_context.prompt_block(chart)
    user = (ctx + "\n\n" if ctx else "") + (hist + "\n\n" if hist else "") + \
        (mem + "\n\n" if mem else "") + \
        "【片段】\n{}\n\n【问题】\n{}".format(build_context(hits), standalone)
    messages = _rag_messages(hits, user, chart)

    attempts = []

    def attempt(spec):
        data, raw, used = _generate_rag(messages, api_key, spec, counter)
        attempts.append({
            "tier": spec.tier,
            "model": spec.model,
            "thinking": spec.thinking,
            "effort": spec.effort,
            "ok": data is not None,
            "usage": used,
        })
        return data, raw

    data, last_raw = attempt(route.spec)
    if data is None:
        out = _failure_rag(hits, standalone, history, counter, last_raw)
    else:
        out = _finalize_rag(
            data, hits, standalone, history, counter,
            require_citations=(chart or {}).get("kind") != "name",
        )

    escalated = False
    escalation_reason = ""
    # 不要求 data 非空：JSON 连续解析失败（data is None）正是最该升级的情况。
    # 但也只有「小模型起手」才谈得上升级：auto 已经把题判成大模型时再升级，
    # 只会拿同一档模型重答一遍，白花钱还多等一轮。
    if not route.forced and route.initial_tier != router.LARGE:
        need, why = router.needs_escalation(out, hits=hits)
        if need:
            escalated = True
            escalation_reason = why
            large_spec = router.spec_for(router.LARGE)
            data2, raw2 = attempt(large_spec)
            if data2 is None:
                out = _failure_rag(hits, standalone, history, counter, raw2)
            else:
                out = _finalize_rag(
                    data2, hits, standalone, history, counter,
                    require_citations=(chart or {}).get("kind") != "name",
                )

    return _attach_route(out, route, attempts, escalated, escalation_reason)


def _finalize_rag(data, hits, standalone, history, counter, require_citations=True):
    """把模型输出整理成对外结构。同步 `answer` 和异步 `answer_stream` 共用，
    保证两条路径的引用校验、拒答归一化完全一致。

    require_citations=False 只给姓名盘用：五格剖象是 1928 年以来的现代体系，
    盘面本身就能答，不能因为没引古籍就标成「不合规输出」。
    """
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
    # 声称能答却没有一条有效引用：不算拒答，但要标成不合规输出。
    # 姓名盘例外（见函数 docstring）。
    data["invalid_output"] = (
        require_citations and bool(data.get("can_answer")) and not valid_nums
    )
    data["rewritten_question"] = standalone
    data["history_turns"] = len(history)
    data["llm_calls"] = counter["llm_calls"]
    if data.get("can_answer") is False and not data.get("answer"):
        data["answer"] = REFUSAL_TEXT
        data["citations"] = []
    return data


async def _stream_generate(client, messages, api_key, spec, counter, on_delta,
                           allow_delta):
    """用指定模型流式生成一次；返回 (data, raw, 是否已下发过正文)。"""
    from answer_stream import AnswerExtractor

    streamed = False
    last_raw = ""
    data = None
    for _ in range(2):  # JSON 解析失败重试一次；已下发过正文则不再重放
        use_delta = on_delta if (on_delta is not None and not streamed and allow_delta) else None
        extractor = AnswerExtractor()
        parts = []
        async for event in client.stream(
            messages,
            api_key=api_key,
            model=spec.model,
            response_format={"type": "json_object"},
            **spec.request_fields(),
        ):
            if event["type"] == "delta":
                parts.append(event["text"])
                if use_delta is not None:
                    text = extractor.feed(event["text"])
                    if text:
                        use_delta(text)
                        streamed = True
            else:
                used = event.get("usage")
                if used:
                    counter.setdefault("usage", []).append(used)
        counter["llm_calls"] += 1
        last_raw = "".join(parts)
        try:
            data = _parse_json(last_raw)
            break
        except json.JSONDecodeError:
            data = None
    return data, last_raw, streamed


async def answer_stream(question, top_k=5, mode="rrf", api_key=None, history=None,
                        memories=None, on_delta=None, on_step=None, client=None,
                        chart=None, tier="auto"):
    """RAG 模式的流式版：检索照旧，生成逐 token 下发。

    检索是同步 numpy 计算，丢线程池；生成走 `llm` 异步客户端 +
    `AnswerExtractor` 从流式 json_object 里增量解出 answer 字段。
    `on_delta` 是预览，调用方以返回值的 answer 为准（拒答归一化会改正文）。
    路由在生成前决定；只有小模型一个字都没下发且输出不可用时才升级，
    避免把已经展示给用户的预览再重放一遍。
    """
    import asyncio

    import chart_context
    import llm
    from conversation import arewrite_question

    client = client or llm.default_client()
    counter = {"llm_calls": 0}
    history = normalize_history(history)
    standalone = await arewrite_question(question, history, api_key=api_key,
                                         counter=counter, client=client)
    route = router.decide(standalone, history=history, chart=chart, tier=tier, mode="rag")
    skip_retrieval = _skip_retrieval(chart)
    if skip_retrieval:
        search_query, hits = "", []
    else:
        search_query = chart_context.retrieval_query(chart, standalone)
        hits = await asyncio.to_thread(retrieve_one, search_query, top_k=top_k, mode=mode)
    if on_step is not None and not skip_retrieval:
        on_step({
            "agent": "retrieval",
            "tool": "retrieve",
            "args": {"query": search_query, "top_k": top_k, "mode": mode},
            "ok": True,
            "chunk_ids": [h["chunk_id"] for h in hits],
            "error": None,
        })

    hist = history_block(history)
    mem = memory_block(memories)
    ctx = chart_context.prompt_block(chart)
    user = ((ctx + "\n\n") if ctx else "") + ((hist + "\n\n") if hist else "") + \
        ((mem + "\n\n") if mem else "") + \
        "【片段】\n{}\n\n【问题】\n{}".format(build_context(hits), standalone)
    messages = _rag_messages(hits, user, chart)

    attempts = [
        {
            "tier": route.spec.tier,
            "model": route.spec.model,
            "thinking": route.spec.thinking,
            "effort": route.spec.effort,
        }
    ]
    data, last_raw, streamed = await _stream_generate(
        client, messages, api_key, route.spec, counter, on_delta, allow_delta=True
    )
    attempts[0]["ok"] = data is not None

    if data is None:
        out = _failure_rag(hits, standalone, history, counter, last_raw)
    else:
        out = _finalize_rag(
            data, hits, standalone, history, counter,
            require_citations=(chart or {}).get("kind") != "name",
        )

    escalated = False
    escalation_reason = ""
    if not streamed and not route.forced and route.initial_tier != router.LARGE:
        need, why = router.needs_escalation(out, hits=hits)
        if need:
            escalated = True
            escalation_reason = why
            large_spec = router.spec_for(router.LARGE)
            attempts.append({
                "tier": large_spec.tier,
                "model": large_spec.model,
                "thinking": large_spec.thinking,
                "effort": large_spec.effort,
            })
            data2, raw2, _ = await _stream_generate(
                client, messages, api_key, large_spec, counter, on_delta, allow_delta=True
            )
            attempts[-1]["ok"] = data2 is not None
            if data2 is None:
                out = _failure_rag(hits, standalone, history, counter, raw2)
            else:
                out = _finalize_rag(
                    data2, hits, standalone, history, counter,
                    require_citations=(chart or {}).get("kind") != "name",
                )

    out["usage"] = llm.merge_usage(counter.get("usage"))
    return _attach_route(out, route, attempts, escalated, escalation_reason)


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    q = " ".join(sys.argv[1:]) or "算命的说我命里带羊刃，这东西还分好几种？"
    print(json.dumps(answer(q), ensure_ascii=False, indent=2))
