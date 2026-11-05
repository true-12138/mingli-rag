import io
import json
import os
from dotenv import load_dotenv
load_dotenv()
import re
import sys
import requests
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from retrieval import retrieve_one
from conversation import history_block, normalize_history, rewrite_question
import usage
import agent_state
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"
REFUSAL_TEXT = "语料中没有足够的依据回答这个问题。"
_CONFIG = agent_state.load_config()
SYSTEM_PROMPT = agent_state.load_prompt("rag_system")
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
def _chat(messages, temperature=0.0, api_key=None):
    resp = requests.post(
        DEEPSEEK_URL,
        headers={
            "Authorization": "Bearer {}".format(_get_api_key(api_key)),
            "Content-Type": "application/json",
        },
        json={
            "model": MODEL,
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        },
        timeout=120,
    )
    resp.raise_for_status()
    payload = resp.json()
    # 旁路累计 token；没有 reset() 的调用方（脚本 / 测试）不记录，不影响行为
    usage.add(payload.get("usage"))
    return payload["choices"][0]["message"]["content"]
def answer(question, top_k=None, mode="rrf", api_key=None, history=None):
    """返回 dict：can_answer / answer / citations / citations_chunk_ids / ...
    can_answer=False 才算一次拒答。
    api_key 用于公网访客自带 key 的场景，不传就读环境变量。
    history 是多轮对话历史；只用于改写追问，不作为回答证据。
    top_k 默认取 Agent State 的 answer_top_k，改它等于改评测口径，会进入 state_version。
    """
    top_k = int(top_k or _CONFIG["answer_top_k"])
    counter = {"llm_calls": 0}
    history = normalize_history(history)
    standalone = rewrite_question(question, history, api_key=api_key, counter=counter)
    hits = retrieve_one(standalone, top_k=top_k, mode=mode)
    hist = history_block(history)
    user = (hist + "\n\n" if hist else "") + "【片段】\n{}\n\n【问题】\n{}".format(
        build_context(hits), standalone)
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
    cited = data.get("citations") or []
    valid_nums, invalid_nums = [], []
    for n in cited:
        if isinstance(n, int) and 1 <= n <= len(hits):
            valid_nums.append(n)
        else:
            invalid_nums.append(n)
    data["citations_chunk_ids"] = [hits[n - 1]["chunk_id"] for n in valid_nums]
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
if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    q = " ".join(sys.argv[1:]) or "算命的说我命里带羊刃，这东西还分好几种？"
    print(json.dumps(answer(q), ensure_ascii=False, indent=2))
