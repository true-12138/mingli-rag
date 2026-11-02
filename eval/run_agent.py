# -*- coding: utf-8 -*-
"""批量跑 Agent 轨迹评测（任务集见 eval/agent_tasks.jsonl）。

默认跑单 Agent 基线（src/agent.py::agent_answer），逐条记录完整 trace，
把能机器判的判据自动判掉，判不了的列进 needs_human 留给人看。

用法::

    export DEEPSEEK_API_KEY=sk-xxxx
    python eval/run_agent.py                     # 全部任务
    python eval/run_agent.py --only a01,b02      # 只跑指定 id
    python eval/run_agent.py --limit 3 -v        # 先跑前 3 条试水
    python eval/run_agent.py --tag multi         # 区分基线 / 多 Agent 两轮结果

输出：eval/results_agent_<tag>.json（逐条 trace + 判定），终端打一张汇总表。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

TASKS_PATH = ROOT / "eval" / "agent_tasks.jsonl"


def die(msg: str) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(1)


# ---------- 依赖检查：给出可执行的提示，而不是一串 ImportError ----------

try:
    import corpus
except ModuleNotFoundError as e:  # pragma: no cover
    die("导入 corpus 失败：{}\n请确认在项目根目录运行，且已 pip install -r requirements.txt".format(e))

try:
    from agent import agent_answer
except ModuleNotFoundError as e:  # pragma: no cover
    missing = getattr(e, "name", None) or str(e)
    die(
        "导入 agent 失败：缺少依赖 `{}`。\n"
        "\n"
        "注意：agent 的导入链会连带加载 tools→fortune（ephem / lunar_python）、\n"
        "rag→python-dotenv、retrieval→rank_bm25+sentence-transformers，\n"
        "少装任何一个都会在这里报错。一次装全：\n"
        "\n"
        "    pip install -r requirements.txt\n"
        "\n"
        "只单独装 sentence-transformers / torch 是不够的。".format(missing)
    )


# ---------- 任务与判据 ----------

def load_tasks(path: Path) -> list[dict]:
    tasks = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            tasks.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise SystemExit("{} 第 {} 行不是合法 JSON：{}".format(path, i, e))
    return tasks


def build_id2book() -> dict[int, str]:
    """chunk_id -> 书名，用于校验引用是否落在期望的书里。"""
    return {c["chunk_id"]: (c.get("meta") or {}).get("book") for c in corpus.load_chunks()}


_TOOL_RE = re.compile(r"^\s*([a-zA-Z_]+)\s*(?:\((.*)\))?\s*$")


def parse_tool_spec(spec: str) -> dict:
    """把 'search_classics(book=穷通宝鉴)' 解析成 {action, book}。"""
    m = _TOOL_RE.match(spec)
    if not m:
        return {"action": spec, "book": None}
    action, args = m.group(1), m.group(2)
    book = None
    if args:
        for part in args.split(","):
            if "=" in part:
                k, v = part.split("=", 1)
                if k.strip() == "book":
                    book = v.strip().strip("\"'")
    return {"action": action, "book": book}


def check_tools(trace: list[dict], specs: list[str]) -> list[dict]:
    """逐个必需工具检查：trace 里有没有一次成功的调用满足 action（和 book）。"""
    out = []
    for spec in specs:
        need = parse_tool_spec(spec)
        hit = None
        for t in trace:
            if t.get("action") != need["action"]:
                continue
            if need["book"]:
                arg_book = (t.get("args") or {}).get("book")
                if not arg_book or need["book"] not in str(arg_book):
                    continue
            if t.get("ok") is False:
                continue
            hit = t.get("step")
            break
        out.append({"need": spec, "ok": hit is not None, "at_step": hit})
    return out


def check_citations(res: dict, evidence_books: list[str], id2book: dict[int, str]) -> dict:
    cited = [int(c) for c in (res.get("citations_chunk_ids") or [])]
    books = [id2book.get(c) for c in cited]
    if not evidence_books:
        return {"cited": cited, "books": books, "ok": None, "note": "该任务不限定出处"}
    ok = any(b in evidence_books for b in books)
    return {"cited": cited, "books": books, "ok": ok, "expect": evidence_books}


def auto_judge(task: dict, res: dict, id2book: dict[int, str]) -> dict:
    """能机器判的判掉，判不了的放进 needs_human。"""
    checks = []
    needs_human = list(task.get("pass_criteria") or [])

    # 1) 步数
    steps_ok = res.get("steps", 0) <= int(task.get("max_steps", 6))
    checks.append({"name": "max_steps", "ok": steps_ok,
                   "detail": "{} / {}".format(res.get("steps"), task.get("max_steps", 6))})
    if steps_ok:
        needs_human = [c for c in needs_human if "步" not in c]

    # 2) 必需工具
    tool_checks = check_tools(res.get("trace") or [], task.get("required_tools") or [])
    for tc in tool_checks:
        checks.append({"name": "tool:" + tc["need"], "ok": tc["ok"], "detail": tc["at_step"]})
    used = {tc["need"] for tc in tool_checks}
    needs_human = [c for c in needs_human if not any(u in c for u in used)]

    # 3) 引用出处
    cit = check_citations(res, task.get("evidence_books") or [], id2book)
    if cit["ok"] is not None:
        checks.append({"name": "citation_book", "ok": cit["ok"],
                       "detail": "{} -> {}".format(cit["cited"], cit["books"])})
        needs_human = [c for c in needs_human if "引用" not in c and "chunk_id" not in c]

    # 4) 拒答类任务：机器只能判「有没有拒」
    if task.get("type") == "拒答":
        refused = res.get("can_answer") is False
        checks.append({"name": "refused", "ok": refused, "detail": res.get("can_answer")})
        # 拒是必要条件，不是充分条件：拒了之后答案里是否夹带倾向性判断还得人看
        if refused:
            needs_human = [c for c in needs_human if "明确拒答" not in c and "明确说明" not in c]
    else:
        answered = res.get("can_answer") is True and not res.get("invalid_output")
        checks.append({"name": "answered", "ok": answered,
                       "detail": "can_answer={} invalid={}".format(res.get("can_answer"), res.get("invalid_output"))})

    return {
        "auto_pass": all(c["ok"] for c in checks),
        "checks": checks,
        "needs_human": needs_human,
        "cited_books": cit["books"],
    }


# ---------- 主流程 ----------

def run(tasks: list[dict], args) -> dict:
    id2book = build_id2book()
    results = []
    t0 = time.time()

    for i, task in enumerate(tasks, start=1):
        tid = task["id"]
        print("[{}/{}] {} {}".format(i, len(tasks), tid, task.get("name", "")), flush=True)
        started = time.time()
        record = {"id": tid, "type": task.get("type"), "name": task.get("name"),
                  "question": task.get("question")}
        try:
            res = agent_answer(task["question"], max_steps=int(task.get("max_steps", 6)))
            record.update({
                "can_answer": res.get("can_answer"),
                "answer": res.get("answer"),
                "citations": res.get("citations_chunk_ids"),
                "invalid_citations": res.get("invalid_citations"),
                "invalid_output": res.get("invalid_output"),
                "refusal_reason": res.get("refusal_reason"),
                "steps": res.get("steps"),
                "trace": res.get("trace"),
            })
            record["judge"] = auto_judge(task, res, id2book)
            status = "PASS" if record["judge"]["auto_pass"] else "FAIL"
        except Exception as e:  # 单条失败不拖垮整批
            record["error"] = "{}: {}".format(type(e).__name__, e)
            record["traceback"] = traceback.format_exc()[-1200:]
            status = "ERR"
        record["seconds"] = round(time.time() - started, 1)
        results.append(record)
        print("    -> {}  {:.1f}s".format(status, record["seconds"]), flush=True)
        if args.verbose and record.get("trace"):
            for t in record["trace"]:
                print("       step {} {:<16} {} -> {}".format(
                    t.get("step"), t.get("action"),
                    (t.get("thought") or "")[:36], t.get("chunk_ids")), flush=True)

    summary = {
        "tag": args.tag,
        "total": len(results),
        "auto_pass": sum(1 for r in results if (r.get("judge") or {}).get("auto_pass")),
        "errors": sum(1 for r in results if r.get("error")),
        "elapsed_seconds": round(time.time() - t0, 1),
        "by_type": {},
    }
    for r in results:
        s = summary["by_type"].setdefault(r["type"], {"n": 0, "pass": 0})
        s["n"] += 1
        if (r.get("judge") or {}).get("auto_pass"):
            s["pass"] += 1

    out = {"summary": summary, "tasks": results}
    out_path = ROOT / "eval" / "results_agent_{}.json".format(args.tag)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    print("\n===== 汇总 =====")
    print("通过 {}/{}，报错 {}，用时 {}s".format(
        summary["auto_pass"], summary["total"], summary["errors"], summary["elapsed_seconds"]))
    for typ, s in summary["by_type"].items():
        print("  {:<4} {}/{}".format(typ, s["pass"], s["n"]))
    print("明细：{}".format(out_path))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="批量跑 Agent 轨迹评测")
    ap.add_argument("--tasks", default=str(TASKS_PATH))
    ap.add_argument("--only", default="", help="逗号分隔的任务 id，如 a01,b02")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 条")
    ap.add_argument("--tag", default="baseline", help="结果文件名后缀，用于区分基线/多 Agent")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    tasks = load_tasks(Path(args.tasks))
    if args.only:
        wanted = {x.strip() for x in args.only.split(",") if x.strip()}
        tasks = [t for t in tasks if t["id"] in wanted]
        missing = wanted - {t["id"] for t in tasks}
        if missing:
            die("任务集里没有这些 id：{}".format(", ".join(sorted(missing))))
    if args.limit:
        tasks = tasks[: args.limit]
    if not tasks:
        die("没有可跑的任务")

    run(tasks, args)


if __name__ == "__main__":
    main()
