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
sys.path.insert(0, str(ROOT / "eval"))

import agent_state  # noqa: E402
import benchmark as benchmark_mod  # noqa: E402
import usage  # noqa: E402

TASKS_PATH = ROOT / "eval" / "agent_tasks.jsonl"
BENCHMARK_PATH = ROOT / "eval" / "tasks" / "agent_v1"


def die(msg: str) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(1)


# ---------- 依赖检查：给出可执行的提示，而不是一串 ImportError ----------

try:
    import corpus
except ModuleNotFoundError as e:  # pragma: no cover
    die("导入 corpus 失败：{}\n请确认在项目根目录运行，且已 pip install -r requirements.txt".format(e))

_AGENT_GUARD = (
    "导入 agent 失败：缺少依赖 `{}`。\n"
    "\n"
    "注意：agent 的导入链会连带加载 tools→fortune（ephem / lunar_python）、\n"
    "rag→python-dotenv、retrieval→rank_bm25+sentence-transformers，\n"
    "少装任何一个都会在这里报错。一次装全：\n"
    "\n"
    "    pip install -r requirements.txt\n"
    "\n"
    "只单独装 sentence-transformers / torch 是不够的。"
)


# ---------- 任务与判据 ----------

def load_legacy_tasks(path: Path) -> list[dict]:
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


def load_tasks(path: Path | None = None, split: str = "all") -> list[dict]:
    """优先读冻结的 Benchmark（公开题面 + 私有判据），没有则退回 legacy JSONL。"""
    if path and not Path(path).exists():
        raise SystemExit("找不到 benchmark：{}".format(path))
    target = Path(path) if path else BENCHMARK_PATH
    if benchmark_mod.available(target):
        return benchmark_mod.load_tasks(target, split=split)
    if split not in ("all", ""):
        raise SystemExit(
            "没有冻结的 Benchmark，--split {} 不可用。"
            "先跑 python eval/build_benchmark.py 生成划分。".format(split))
    legacy = TASKS_PATH if path is None else Path(path)
    if not legacy.exists():
        raise SystemExit("没有可用的任务集：{}".format(legacy))
    return load_legacy_tasks(legacy)


def run_index_from_tag(tag: str) -> int:
    """从 tag 里取第几次运行：multi_r3 -> 3，baseline -> 1。"""
    m = re.search(r"(?:^|_)r(\d+)$", tag or "")
    return int(m.group(1)) if m else 1


def check_prediction(pred: dict, results: list[dict]) -> dict:
    """对照「跑之前写下的预测」与「跑完的结果」。

    预测正确的 case 不是重点；重点是把「预测会翻绿但没翻」的 case 单独列出来，
    它们是下一轮假设的输入。这一步必须在看结果之前写，否则只是事后解释。
    """
    actual = {r["id"] for r in results if (r.get("judge") or {}).get("auto_pass")}
    want_pass = set(pred.get("predicted_pass") or [])
    want_fail = set(pred.get("predicted_fail") or [])
    missed = sorted(want_pass - actual)      # 预测过、实际没过
    unexpected = sorted(want_fail & actual)  # 预测不过、实际过了
    confirmed = sorted(want_pass & actual)
    return {
        "hypothesis": pred.get("hypothesis"),
        "round": pred.get("round"),
        "predicted_pass": sorted(want_pass),
        "predicted_fail": sorted(want_fail),
        "confirmed": confirmed,
        "missed": missed,
        "unexpected": unexpected,
        "ok": not missed and not unexpected,
    }


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


def _book_match(need: str, arg: str | None) -> bool:
    """book 参数按书名片段匹配：系统提示明确允许传片段（「子平真诠」指《子平真诠评注》），
    所以两个方向都算命中，不能只判 need in arg。"""
    if not arg:
        return False
    return need in str(arg) or str(arg) in need


def check_tools(trace: list[dict], specs: list[str], cited_books: list[str] | None = None) -> list[dict]:
    """逐个必需工具检查。

    search_classics(book=X) 的含义是「必须查到 X 这本书」，满足方式有两种：
      1) 显式 book=X 检索成功；
      2) 引用了来自 X 的 chunk（引用必须来自本次 trace，等价于查到了）。
    记录 via 便于分辨是哪种，跑 A/B 时需要知道有多少条是「全局检索顺带命中」。
    """
    cited_books = cited_books or []
    out = []
    for spec in specs:
        need = parse_tool_spec(spec)
        hit, via = None, None
        for t in trace:
            if t.get("action") != need["action"] or t.get("ok") is False:
                continue
            if need["book"] and not _book_match(need["book"], (t.get("args") or {}).get("book")):
                continue
            hit, via = t.get("step"), "book_arg"
            break
        if hit is None and need["book"] and need["book"] in cited_books:
            hit, via = "cited", "citation"
        out.append({"need": spec, "ok": hit is not None, "at_step": hit, "via": via})
    return out


def check_citations(res: dict, evidence_books: list[str], id2book: dict[int, str]) -> dict:
    cited = [int(c) for c in (res.get("citations_chunk_ids") or [])]
    books = [id2book.get(c) for c in cited]
    if not evidence_books:
        return {"cited": cited, "books": books, "ok": None, "note": "该任务不限定出处"}
    ok = any(b in evidence_books for b in books)
    return {"cited": cited, "books": books, "ok": ok, "expect": evidence_books}


def auto_judge(task: dict, res: dict, id2book: dict[int, str]) -> dict:
    """能机器判的判掉，判不了的放进 needs_human。

    diagnostics 不参与通过判定，只记录过程质量：
    dual_book_explicit = 判据里点名的每一本书，是不是都用 book= 显式检索过。
    单 Agent 常靠一次全局检索顺带命中两本书（via=citation），形式上过、实质上没做多跳，
    这个字段就是为了把这种情况显出来。
    """
    checks = []
    needs_human = list(task.get("pass_criteria") or [])

    # 1) 步数
    steps_ok = res.get("steps", 0) <= int(task.get("max_steps", 6))
    checks.append({"name": "max_steps", "ok": steps_ok,
                   "detail": "{} / {}".format(res.get("steps"), task.get("max_steps", 6))})
    if steps_ok:
        needs_human = [c for c in needs_human if "步" not in c]

    # 2) 引用出处（先算，工具判据要用到「引用了哪本书」）
    cit = check_citations(res, task.get("evidence_books") or [], id2book)
    if cit["ok"] is not None:
        checks.append({"name": "citation_book", "ok": cit["ok"],
                       "detail": "{} -> {}".format(cit["cited"], cit["books"])})
        needs_human = [c for c in needs_human if "引用" not in c and "chunk_id" not in c]

    # 3) 必需工具
    tool_checks = check_tools(res.get("trace") or [], task.get("required_tools") or [], cit["books"])
    for tc in tool_checks:
        checks.append({"name": "tool:" + tc["need"], "ok": tc["ok"],
                       "detail": {"at_step": tc["at_step"], "via": tc["via"]}})
    used = {tc["need"] for tc in tool_checks}
    needs_human = [c for c in needs_human if not any(u in c for u in used)]

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

    book_specs = [tc for tc in tool_checks if parse_tool_spec(tc["need"])["book"]]
    return {
        "auto_pass": all(c["ok"] for c in checks),
        "checks": checks,
        "needs_human": needs_human,
        "cited_books": cit["books"],
        "diagnostics": {
            "dual_book_explicit": bool(book_specs) and all(tc["via"] == "book_arg" for tc in book_specs),
            "book_specs": [{k: tc[k] for k in ("need", "ok", "via")} for tc in book_specs],
        },
    }


# ---------- 主流程 ----------

def get_agent(name: str):
    """延迟导入：--rescore 只判旧结果，不需要加载 embedding 模型和排盘依赖。"""
    try:
        if name == "multi":
            from agent_multi import agent_answer as fn
        else:
            from agent import agent_answer as fn
    except ModuleNotFoundError as e:  # pragma: no cover
        die(_AGENT_GUARD.format(getattr(e, "name", None) or str(e)))
    return fn


def benchmark_info(path) -> dict:
    if path and benchmark_mod.available(path):
        return benchmark_mod.verify(path)
    if not path and benchmark_mod.available(BENCHMARK_PATH):
        return benchmark_mod.verify(BENCHMARK_PATH)
    return {"ok": True, "frozen": False, "version": None, "status": None, "splits": None}


def run(tasks: list[dict], args) -> dict:
    id2book = build_id2book()
    solve = get_agent(args.agent)
    state = agent_state.manifest()
    bench = benchmark_info(args.benchmark)
    run_index = args.run_index or run_index_from_tag(args.tag)
    results = []
    t0 = time.time()

    print("Agent State: {} · benchmark {} · run #{}{}".format(
        agent_state.short(state["version"]), bench.get("version") or "legacy",
        run_index, "" if bench.get("ok", True) else " · !! 题面已被改动，结果不可与旧 run 直接比"))
    if bench.get("splits"):
        print("划分：{}".format(bench["splits"]))

    for i, task in enumerate(tasks, start=1):
        tid = task["id"]
        print("[{}/{}] {} {}".format(i, len(tasks), tid, task.get("name", "")), flush=True)
        started = time.time()
        record = {"id": tid, "type": task.get("type"), "name": task.get("name"),
                  "question": task.get("question")}
        usage.reset()  # 每题单独计 token，才能回答「这条用例花了多少」
        try:
            res = solve(task["question"], max_steps=int(task.get("max_steps", 6)))
            record["usage"] = usage.snapshot() or {}
            record.update({
                "can_answer": res.get("can_answer"),
                "answer": res.get("answer"),
                "citations": res.get("citations_chunk_ids"),
                "invalid_citations": res.get("invalid_citations"),
                "invalid_output": res.get("invalid_output"),
                "refusal_reason": res.get("refusal_reason"),
                "steps": res.get("steps"),
                "llm_calls": res.get("llm_calls"),
                "plan": res.get("plan"),
                "verdict": res.get("verdict"),
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

    duals = [((r.get("judge") or {}).get("diagnostics") or {}) for r in results]
    duals = [d for d in duals if d.get("book_specs")]  # 只统计点名了书的题
    summary = {
        "tag": args.tag,
        "agent": args.agent,
        "total": len(results),
        "auto_pass": sum(1 for r in results if (r.get("judge") or {}).get("auto_pass")),
        "dual_book_explicit": sum(1 for d in duals if d["dual_book_explicit"]),
        "dual_book_applicable": len(duals),
        "errors": sum(1 for r in results if r.get("error")),
        "elapsed_seconds": round(time.time() - t0, 1),
        "by_type": {},
        # 归因：这次 run 用的是哪版 Agent、哪版题目、第几次跑
        "state_version": state["version"],
        "state_manifest": state,
        "benchmark_version": bench.get("version"),
        "benchmark_frozen": bench.get("frozen"),
        "benchmark_ok": bench.get("ok"),
        "split": args.split,
        "run_index": run_index,
    }
    for r in results:
        s = summary["by_type"].setdefault(r["type"], {"n": 0, "pass": 0})
        s["n"] += 1
        if (r.get("judge") or {}).get("auto_pass"):
            s["pass"] += 1
    calls = [r["llm_calls"] for r in results if isinstance(r.get("llm_calls"), int)]
    if calls:
        summary["llm_calls"] = {"total": sum(calls), "mean": round(sum(calls) / len(calls), 1)}
        # 每通过一题要多少次 LLM 调用：多 Agent 的「更准」要连同这个数一起看
        if summary["auto_pass"]:
            summary["llm_calls_per_pass"] = round(sum(calls) / summary["auto_pass"], 2)
    tokens = [r["usage"].get("total_tokens", 0) for r in results if r.get("usage")]
    if any(tokens):
        summary["total_tokens"] = sum(tokens)
        if summary["auto_pass"]:
            summary["tokens_per_pass"] = round(sum(tokens) / summary["auto_pass"], 1)

    out = {"summary": summary, "tasks": results}
    if args.predict:
        pred = json.loads(Path(args.predict).read_text(encoding="utf-8"))
        out["prediction"] = check_prediction(pred, results)

    out_path = ROOT / "eval" / "results_agent_{}.json".format(args.tag)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    print("\n===== 汇总 =====")
    print("[{}] 通过 {}/{}，报错 {}，用时 {}s".format(
        args.agent, summary["auto_pass"], summary["total"],
        summary["errors"], summary["elapsed_seconds"]))
    print("  state {} · benchmark {} · run #{}".format(
        agent_state.short(summary["state_version"]),
        summary.get("benchmark_version") or "legacy", run_index))
    print("  双书显式检索 {}/{}（只算点了名的题；诊断项，不计入通过）".format(
        summary["dual_book_explicit"], summary["dual_book_applicable"]))
    if "llm_calls" in summary:
        print("  LLM 调用 {} 次，均值 {}{}".format(
            summary["llm_calls"]["total"], summary["llm_calls"]["mean"],
            "，每通过一题 {:.2f} 次".format(summary["llm_calls_per_pass"])
            if summary.get("llm_calls_per_pass") else ""))
    if "total_tokens" in summary:
        print("  token {}，每通过一题 {}".format(
            summary["total_tokens"], summary.get("tokens_per_pass")))
    for typ, s in summary["by_type"].items():
        print("  {:<4} {}/{}".format(typ, s["pass"], s["n"]))

    check = out.get("prediction")
    if check:
        print("\n===== 预测对照（跑之前写下的） =====")
        print("  假设：{}".format(check.get("hypothesis") or "（未写）"))
        print("  预测翻绿且确实翻绿：{}".format(", ".join(check["confirmed"]) or "—"))
        print("  预测翻绿但没翻：{}".format(", ".join(check["missed"]) or "—"))
        print("  预测失败但过了：{}".format(", ".join(check["unexpected"]) or "—"))
        print("  -> 下一步假设应优先从「没翻」的那几条里找。")

    print("明细：{}".format(out_path))

    if args.record:
        try:
            import evalhub

            run_id = evalhub.record_agent_run(
                out, out_path.name,
                state_version=summary["state_version"],
                benchmark_version=summary.get("benchmark_version"),
                run_index=run_index,
                state_manifest=state,
            )
            print("评测账本：run id {}（source {}）".format(run_id, out_path.name))
        except Exception as e:  # 记账失败不该让一次已经跑完的评测作废
            print("! 写入评测账本失败（结果文件已保存）：{}".format(e))

    return out


def rescore(path: Path, tasks: list[dict]) -> None:
    """不重跑 API，用已有结果重新判一遍（加了新判据/诊断项时用）。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    id2book = build_id2book()
    by_id = {t["id"]: t for t in tasks}
    rows = []
    for rec in data.get("tasks") or []:
        task = by_id.get(rec["id"])
        if not task:
            continue
        if rec.get("error"):
            rows.append((rec["id"], "ERR", None))
            continue
        # 结果文件里存的是 citations，auto_judge 认的是 citations_chunk_ids
        res = dict(rec, citations_chunk_ids=rec.get("citations") or [])
        judge = auto_judge(task, res, id2book)
        rec["judge"] = judge
        rows.append((rec["id"], "PASS" if judge["auto_pass"] else "FAIL", judge))
    base = path.with_name(path.stem + "_rescored.json")
    base.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    n_pass = sum(1 for _, s, _ in rows if s == "PASS")
    duals = [j["diagnostics"] for _, _, j in rows
             if j and j["diagnostics"].get("book_specs")]
    n_dual = sum(1 for d in duals if d["dual_book_explicit"])
    print("{} 条，通过 {}/{}，双书显式 {}/{}（只算点了名的题）".format(
        path.name, n_pass, len(rows), n_dual, len(duals)))
    print("写出：{}".format(base))


def main() -> None:
    ap = argparse.ArgumentParser(description="批量跑 Agent 轨迹评测")
    ap.add_argument("--benchmark", default=None,
                    help="冻结的 Benchmark 目录，默认 eval/tasks/agent_v1")
    ap.add_argument("--tasks", default=None,
                    help="legacy 任务文件（eval/agent_tasks.jsonl）；给 --benchmark 时忽略")
    ap.add_argument("--split", default="all", choices=("all", "dev", "holdout"),
                    help="只跑某一切分；holdout 自冻结起不应参与调参")
    ap.add_argument("--only", default="", help="逗号分隔的任务 id，如 a01,b02")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 条")
    ap.add_argument("--tag", default="baseline", help="结果文件名后缀，用于区分基线/多 Agent")
    ap.add_argument("--run-index", type=int, default=0,
                    help="同一实验的第几次运行；不传则从 tag 的 _rN 推断")
    ap.add_argument("--agent", default="single", choices=("single", "multi"),
                    help="single=src/agent.py，multi=src/agent_multi.py")
    ap.add_argument("--predict", default="",
                    help="跑之前写好的预测 JSON（eval/rounds/*.json），跑完自动对照")
    ap.add_argument("--record", dest="record", action="store_true", default=True,
                    help="把结果写进评测账本（默认开）")
    ap.add_argument("--no-record", dest="record", action="store_false",
                    help="只写结果文件，不记账本")
    ap.add_argument("--rescore", default="",
                    help="不跑 API，用已有结果文件重新判一遍（加新诊断项时用）")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    if args.benchmark:
        tasks = load_tasks(Path(args.benchmark), split=args.split)
    elif args.tasks:
        tasks = load_legacy_tasks(Path(args.tasks))
    else:
        tasks = load_tasks(None, split=args.split)

    if args.rescore:
        # 重判要用全部题目，不受 --split / --only 影响
        rescore(Path(args.rescore), load_tasks(None, split="all"))
        return
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
