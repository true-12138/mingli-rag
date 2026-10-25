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
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"
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
5. 只输出 JSON，不要输出 JSON 以外的任何文字。
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
def _get_api_key():
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise SystemExit(
            "没有找到 DEEPSEEK_API_KEY。先执行：\n"
            "  export DEEPSEEK_API_KEY=sk-xxxx\n"
            "再运行。不要把 key 写进代码或提交到 git。"
        )
    return key
def build_context(hits):
    lines = []
    for i, h in enumerate(hits, 1):
        m = h["meta"]
        title = "《{}·{}·{}》".format(
            m.get("book", ""), m.get("volume", ""), m.get("chapter", "")
        )
        lines.append("[{}] {}\n{}".format(i, title, h["text"]))
    return "\n\n".join(lines)
def _parse_json(raw):
    raw = raw.strip()
    # 防止模型偶尔套 ```json 围栏
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)
def _chat(messages, temperature=0.0):
    resp = requests.post(
        DEEPSEEK_URL,
        headers={
            "Authorization": "Bearer {}".format(_get_api_key()),
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
    return resp.json()["choices"][0]["message"]["content"]
def answer(question, top_k=5, mode="rrf"):
    """返回 dict：can_answer / answer / citations / citations_chunk_ids / ...
    can_answer=False 才算一次拒答。
    """
    hits = retrieve_one(question, top_k=top_k, mode=mode)
    user = "【片段】\n{}\n\n【问题】\n{}".format(build_context(hits), question)
    data = None
    last_raw = ""
    for _ in range(2):  # JSON 解析失败重试一次
        last_raw = _chat(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ]
        )
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
    if data.get("can_answer") is False and not data.get("answer"):
        data["answer"] = REFUSAL_TEXT
        data["citations"] = []
    return data
if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    q = " ".join(sys.argv[1:]) or "算命的说我命里带羊刃，这东西还分好几种？"
    print(json.dumps(answer(q), ensure_ascii=False, indent=2))
