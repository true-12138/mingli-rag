# -*- coding: utf-8 -*-
"""批量跑多轮对话评测（对话集见 eval/multiturn.jsonl）。

每条对话按顺序跑，上一轮的回答会作为下一轮 history 传回去；每轮记录：
原始问题、改写后的问题（rewritten_question）、回答、引用 chunk、完整 trace。
判定只做机械可判的部分：

- 改写是否补回了指代/省略（rewrite_groups 每组至少命中一个词）；
- 引用是否落在期望的书里；
- 换书后有没有把旧书的 chunk 当证据（forbidden_books）；
- 拒答轮是否真的零引用；
- 跨轮工具约束是否被遵守（forbidden_tools）。

判不了的（比如「四病四药说得全不全」）留给人工，不假装自动通过。

用法::

    export DEEPSEEK_API_KEY=sk-xxxx        # 只在自己的终端里 export
    python eval/run_multiturn.py            # 全部 20 条，单 Agent
    python eval/run_multiturn.py --agent multi
    python eval/run_multiturn.py --only mt01,mt16 -v
    python eval/run_multiturn.py --rescore eval/results_multiturn_baseline.json

输出：eval/results_multiturn_<tag>.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

TASKS_PATH = ROOT / "eval" / "multiturn.jsonl"


def die(msg: str) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(1)


try:
    import corpus
except ModuleNotFoundError as e:  # pragma: no cover
    die("导入 corpus 失败：{}\n请确认在项目根目录运行，且已 pip install -r requirements.txt".format(e))


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
    return {int(c["chunk_id"]): (c.get("meta") or {}).get("book") or "" for c in corpus.load_chunks()}


def get_agent(name: str):
    try:
        if name == "multi":
            from agent_multi import agent_answer as fn
        else:
            from agent import agent_answer as fn
    except ModuleNotFoundError as e:  # pragma: no cover
        die("导入 agent 失败：缺少依赖 `{}`。\n一次装全：pip install -r requirements.txt".format(
            getattr(e, "name", None) or str(e)))
    return fn


# ---------- 单轮判定 ----------

def _cited_books(rec: dict, id2book: dict[int, str]) -> list[str]:
    books = []
    for cid in rec.get("citations") or []:
        try:
            books.append(id2book.get(int(cid), ""))
        except (TypeError, ValueError):
            books.append("")
    return books


def _trace_actions(rec: dict) -> list[str]:
    return [str(t.get("action")) for t in (rec.get("trace") or [])
            if t.get("action") and t.get("ok") is not False]


def judge_turn(spec: dict, rec: dict, id2book: dict[int, str]) -> dict:
    """按 turn 里写明的检查项逐条判；返回 checks / problems / pass。

    没有写检查项的轮次只记录、不判，避免把「没设判据」当成「通过」。
    """
    answer = rec.get("answer") or ""
    rewritten = rec.get("rewritten_question") or ""
    books = _cited_books(rec, id2book)
    actions = _trace_actions(rec)
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    for group in spec.get("rewrite_groups") or []:
        hit = [t for t in group if t in rewritten]
        add("rewrite:" + "|".join(group), bool(hit),
            "命中 {}；改写={!r}".format(hit, rewritten[:120]))

    if "expect_refusal" in spec:
        ok = (rec.get("can_answer") is False) and not (rec.get("citations") or [])
        add("refusal", ok, "can_answer={} citations={}".format(
            rec.get("can_answer"), rec.get("citations")))

    if spec.get("expected_books"):
        add("expected_books", any(b in spec["expected_books"] for b in books),
            "引用书={} 期望={}".format(books, spec["expected_books"]))

    if spec.get("forbidden_books"):
        bad = [b for b in books if b in spec["forbidden_books"]]
        add("forbidden_books", not bad,
            "违规引用={} 禁止={}".format(bad, spec["forbidden_books"]))

    if spec.get("forbidden_tools"):
        bad = [a for a in actions if a in spec["forbidden_tools"]]
        add("forbidden_tools", not bad,
            "违规调用={} 禁止={}".format(bad, spec["forbidden_tools"]))

    if spec.get("must_call_tools"):
        missing = [a for a in spec["must_call_tools"] if a not in actions]
        add("must_call_tools", not missing, "缺少调用={}".format(missing))

    for text in spec.get("must_contain") or []:
        add("must_contain:" + text, text in answer, "回答前 120 字={!r}".format(answer[:120]))

    for group in spec.get("must_contain_any") or []:
        hit = [t for t in group if t in answer]
        add("must_contain_any:" + "|".join(group), bool(hit), "命中={}".format(hit))

    for text in spec.get("must_not_contain") or []:
        add("must_not_contain:" + text, text not in answer, "")

    if rec.get("invalid_citations"):
        add("citation_integrity", False, "非法引用={}".format(rec["invalid_citations"]))
    if rec.get("invalid_output"):
        add("citation_integrity", False, "声称能答但没有有效引用")

    problems = [c["name"] + "：" + c["detail"] for c in checks if not c["ok"]]
    return {
        "checked": bool(checks),
        "pass": bool(checks) and not problems,
        "checks": checks,
        "problems": problems,
        "needs_human": not checks,
    }


def judge_conversation(task: dict, turn_records: list[dict], id2book: dict[int, str]) -> dict:
    if len(turn_records) != len(task["turns"]):
        return {
            "auto_pass": False,
            "turns": [{"checked": True, "pass": False, "checks": [],
                       "problems": ["轮次缺失：应有 {} 轮，实际 {} 轮".format(
                           len(task["turns"]), len(turn_records))],
                       "needs_human": False}],
            "needs_human": False,
        }
    judges = []
    for spec_turn, rec in zip(task["turns"], turn_records):
        if rec.get("error"):
            judges.append({"checked": True, "pass": False, "checks": [],
                           "problems": ["error：" + rec["error"]], "needs_human": False})
            continue
        judges.append(judge_turn(spec_turn, rec, id2book))
    checked = [j for j in judges if j["checked"]]
    return {
        "auto_pass": bool(checked) and all(j["pass"] for j in checked),
        "turns": judges,
        "needs_human": any(j["needs_human"] for j in judges),
    }


# ---------- 跑批 ----------

def _scrub(obj, secret: str):
    """结果文件里绝不能出现 API key；调用方可能把 key 带进异常字符串。"""
    if not secret:
        return obj
    if isinstance(obj, str):
        return obj.replace(secret, "***")
    if isinstance(obj, dict):
        return {k: _scrub(v, secret) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub(v, secret) for v in obj]
    return obj


def run(tasks: list[dict], args) -> dict:
    secret = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not secret:
        die("没有 DEEPSEEK_API_KEY。请在自己的终端里 export 后再跑：\n"
            "  export DEEPSEEK_API_KEY=sk-xxxx\n"
            "不要把 key 写进 .env、命令行参数或聊天窗口。")

    id2book = build_id2book()
    solve = get_agent(args.agent)
    results = []
    t0 = time.time()

    for i, task in enumerate(tasks, start=1):
        print("[{}/{}] {} {}".format(i, len(tasks), task["id"], task.get("name", "")), flush=True)
        started = time.time()
        history = []
        turn_records = []
        record = {"id": task["id"], "category": task.get("category"),
                  "name": task.get("name"), "note": task.get("note"), "turns": turn_records}

        for idx, turn_spec in enumerate(task["turns"]):
            q = turn_spec["question"]
            rec = {"turn": idx, "question": q}
            try:
                res = solve(q, max_steps=args.max_steps, history=history)
                rec.update({
                    "rewritten_question": res.get("rewritten_question"),
                    "can_answer": res.get("can_answer"),
                    "answer": res.get("answer"),
                    "citations": res.get("citations_chunk_ids"),
                    "citation_books": _cited_books(
                        {"citations": res.get("citations_chunk_ids")}, id2book),
                    "invalid_citations": res.get("invalid_citations"),
                    "invalid_output": res.get("invalid_output"),
                    "refusal_reason": res.get("refusal_reason"),
                    "steps": res.get("steps"),
                    "llm_calls": res.get("llm_calls"),
                    "trace": res.get("trace"),
                })
                history.append({"role": "user", "content": q})
                history.append({"role": "assistant", "content": res.get("answer") or ""})
            except Exception as e:  # 单轮失败：记录后停止这条对话，后续轮次没有上下文可依
                rec["error"] = "{}: {}".format(type(e).__name__, e)
                rec["traceback"] = traceback.format_exc()[-1200:]
                turn_records.append(rec)
                break

            judge = judge_turn(turn_spec, rec, id2book)
            rec["judge"] = judge
            turn_records.append(rec)
            if args.verbose:
                print("   turn{} rewrite={!r}".format(idx, rec.get("rewritten_question")), flush=True)
                print("          -> {}  citations={} books={}".format(
                    "PASS" if judge["pass"] else "FAIL",
                    rec.get("citations"), rec.get("citation_books")), flush=True)
                for t in rec.get("trace") or []:
                    print("          step {} {:<16} -> {}".format(
                        t.get("step"), t.get("action"), t.get("chunk_ids")), flush=True)

        judge = judge_conversation(task, turn_records, id2book)
        record["judge"] = judge
        record["seconds"] = round(time.time() - started, 1)
        results.append(record)
        print("    -> {}  {:.1f}s".format("PASS" if judge["auto_pass"] else "FAIL",
                                          record["seconds"]), flush=True)

    summary = {
        "tag": args.tag,
        "agent": args.agent,
        "total": len(results),
        "auto_pass": sum(1 for r in results if r["judge"]["auto_pass"]),
        "errors": sum(1 for r in results if any(t.get("error") for t in r["turns"])),
        "elapsed_seconds": round(time.time() - t0, 1),
        "by_category": {},
    }
    rewrite_pass = rewrite_total = 0
    isolation_violations = 0
    for r in results:
        cat = r["category"]
        s = summary["by_category"].setdefault(cat, {"n": 0, "pass": 0})
        s["n"] += 1
        s["pass"] += int(r["judge"]["auto_pass"])
        for t in r["turns"]:
            for c in (t.get("judge") or {}).get("checks") or []:
                if c["name"].startswith("rewrite:"):
                    rewrite_total += 1
                    rewrite_pass += int(c["ok"])
                if c["name"] == "forbidden_books" and not c["ok"]:
                    isolation_violations += 1
    if rewrite_total:
        summary["rewrite_accuracy"] = {
            "pass": rewrite_pass, "total": rewrite_total,
            "rate": round(rewrite_pass / rewrite_total, 4),
        }
    summary["isolation_violations"] = isolation_violations

    out = {"summary": summary, "tasks": results}
    out = _scrub(out, secret)
    out_path = ROOT / "eval" / "results_multiturn_{}.json".format(args.tag)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    print("\n===== 汇总 =====")
    print("[{}] 对话通过 {}/{}，报错 {}，用时 {}s".format(
        args.agent, summary["auto_pass"], summary["total"],
        summary["errors"], summary["elapsed_seconds"]))
    if rewrite_total:
        print("  改写检查 {}/{}（{:.1%}）".format(
            rewrite_pass, rewrite_total, rewrite_pass / rewrite_total))
    print("  引用隔离违规 {} 次".format(isolation_violations))
    for cat, s in summary["by_category"].items():
        print("  {:<6} {}/{}".format(cat, s["pass"], s["n"]))
    print("明细：{}".format(out_path))
    return out


def rescore(path: Path, tasks: list[dict]) -> None:
    """不重跑 API，用已有结果重新判（改了判据时用）。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    id2book = build_id2book()
    by_id = {t["id"]: t for t in tasks}
    n_pass = 0
    rows = []
    for rec in data.get("tasks") or []:
        task = by_id.get(rec["id"])
        if not task:
            continue
        judge = judge_conversation(task, rec.get("turns") or [], id2book)
        rec["judge"] = judge
        n_pass += int(judge["auto_pass"])
        rows.append((rec["id"], judge))
    base = path.with_name(path.stem + "_rescored.json")
    base.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print("{} 条，对话通过 {}/{}".format(path.name, n_pass, len(rows)))
    for rid, judge in rows:
        if not judge["auto_pass"]:
            print("  FAIL {}：{}".format(rid, "; ".join(
                p for t in judge["turns"] for p in t.get("problems") or [])))
    print("写出：{}".format(base))


def main() -> None:
    ap = argparse.ArgumentParser(description="批量跑多轮对话评测")
    ap.add_argument("--tasks", default=str(TASKS_PATH))
    ap.add_argument("--only", default="", help="逗号分隔的对话 id，如 mt01,mt16")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--tag", default="baseline", help="结果文件名后缀")
    ap.add_argument("--agent", default="single", choices=("single", "multi"))
    ap.add_argument("--max-steps", type=int, default=6)
    ap.add_argument("--rescore", default="")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    tasks = load_tasks(Path(args.tasks))
    if args.rescore:
        rescore(Path(args.rescore), tasks)
        return
    if args.only:
        wanted = {x.strip() for x in args.only.split(",") if x.strip()}
        tasks = [t for t in tasks if t["id"] in wanted]
        missing = wanted - {t["id"] for t in tasks}
        if missing:
            die("对话集里没有这些 id：{}".format(", ".join(sorted(missing))))
    if args.limit:
        tasks = tasks[: args.limit]
    if not tasks:
        die("没有可跑的对话")
    run(tasks, args)


if __name__ == "__main__":
    main()
