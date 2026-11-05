# -*- coding: utf-8 -*-
"""把多次 run 的结果并排比，给出均值与波动区间。

用法::

    python eval/compare_runs.py eval/results_agent_*.json

同一个 agent（single / multi）的多次 run 会被归成一组；
报告里只写「均值 [最小-最大]」，不写单次最高值——单次最高值没有意义。
_rescored.json 是重判产物，默认跳过。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


def _ids_after(flag: str) -> list[int]:
    """取 `--accept 12 13 14` 后面的整数列表，遇到下一个 --flag 停。"""
    if flag not in sys.argv:
        return []
    out = []
    for token in sys.argv[sys.argv.index(flag) + 1:]:
        if token.startswith("--"):
            break
        try:
            out.append(int(token))
        except ValueError:
            break
    return out


def _db_report() -> bool:
    """账本模式：--accept/--candidate 判接受，--matrix 看 case × run。

    返回 True 表示已经处理完，不再走逐文件比较。
    """
    ref = _ids_after("--accept")
    cand = _ids_after("--candidate")
    matrix_ids = _ids_after("--matrix")
    if not ref and not matrix_ids:
        return False

    import evalhub

    if ref:
        result = evalhub.accept_candidate(ref, cand)
        result.pop("reference_runs", None)
        result.pop("candidate_runs", None)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return True

    matrix = evalhub.case_matrix(matrix_ids)
    s = matrix["summary"]
    print("runs={} cases={} 翻转 {}（{:.0%}） 稳定通过 {}（{:.0%}）".format(
        s["n_runs"], s["n_cases"], s["flip"], s["flip_rate"] or 0,
        s["stable_pass"], s["stable_pass_rate"] or 0))
    for case in matrix["cases"]:
        flag = "flip" if case["flip"] else ("pass" if case["stable_pass"] else "fail")
        print("  {:<6} {:<5} {}/{}  {}".format(
            case["case_id"], flag, case["passes"], case["total"],
            "".join("P" if x else "F" for x in case["runs"])))
    return True


def load(paths):
    rows = []
    for p in paths:
        p = Path(p)
        if p.name.endswith("_rescored.json"):
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print("跳过 {}：{}".format(p.name, e))
            continue
        s = d.get("summary") or {}
        tasks = d.get("tasks") or []
        # 老结果文件（加诊断列之前跑的）没有 summary 里的这一项，从逐条诊断里补算
        if s.get("dual_book_explicit") is None:
            dg = [((t.get("judge") or {}).get("diagnostics") or {}) for t in tasks]
            dg = [x for x in dg if x.get("book_specs")]
            s = dict(s, dual_book_explicit=sum(1 for x in dg if x["dual_book_explicit"]),
                     dual_book_applicable=len(dg))
        rows.append({
            "file": p.name,
            "agent": s.get("agent") or ("multi" if "multi" in p.name else "single"),
            "tag": s.get("tag"),
            "pass": s.get("auto_pass", 0),
            "total": s.get("total", len(tasks)),
            "dual": s.get("dual_book_explicit"),
            "dual_n": s.get("dual_book_applicable"),
            "errors": s.get("errors", 0),
            "seconds": s.get("elapsed_seconds"),
            "llm": (s.get("llm_calls") or {}).get("mean"),
            "by_type": s.get("by_type") or {},
            "tasks": tasks,
        })
    return rows


def _span(vals):
    vals = [v for v in vals if isinstance(v, (int, float))]
    if not vals:
        return "—"
    return "{:.1f} [{}-{}]".format(sum(vals) / len(vals), min(vals), max(vals))


def _per_task(rows):
    """哪些任务在多组 run 之间翻转了——这些是最不该拿来做结论的。"""
    seen = {}
    for r in rows:
        for t in r["tasks"]:
            ok = (t.get("judge") or {}).get("auto_pass")
            key = (r["agent"], t["id"])
            seen.setdefault(key, []).append(bool(ok))
    flips = []
    for (agent, tid), oks in sorted(seen.items()):
        if len(oks) > 1 and len(set(oks)) > 1:
            flips.append((agent, tid, "".join("P" if o else "F" for o in oks)))
    return flips


def main():
    if _db_report():
        return

    paths = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not paths:
        print("用法：\n"
              "  python eval/compare_runs.py eval/results_agent_*.json\n"
              "  python eval/compare_runs.py --accept 12 13 14 --candidate 15 16 17\n"
              "  python eval/compare_runs.py --matrix 12 13 14")
        raise SystemExit(1)
    rows = load(paths)
    if not rows:
        print("没有可用的结果文件")
        return

    print("文件                                    agent   通过    双书显式  报错  用时    LLM/题")
    for r in rows:
        print("{:<38} {:<7} {:>2}/{:<2}  {:>4}/{:<4}  {:>4}  {:>6}  {:>5}".format(
            r["file"], r["agent"], r["pass"], r["total"],
            r["dual"] if r["dual"] is not None else "-", r["dual_n"] or "-",
            r["errors"], r["seconds"] if r["seconds"] is not None else "-",
            r["llm"] if r["llm"] is not None else "-"))

    groups = {}
    for r in rows:
        groups.setdefault(r["agent"], []).append(r)

    print("\n===== 分组均值 [最小-最大] =====")
    for agent, rs in sorted(groups.items()):
        n = len(rs)
        line = "{}（{} 次）：通过 {} / {}".format(
            agent, n, _span([r["pass"] for r in rs]), rs[0]["total"])
        # 加诊断列之前跑的老结果 dual_n 是 0，不能算进均值，否则会把分母和分数都拉低
        duals = [(r["dual"], r["dual_n"]) for r in rs if r.get("dual_n")]
        if duals:
            line += "，双书显式 {}".format(
                _span([d for d, _ in duals]) + " / " + str(duals[0][1]))
        line += "，用时 {}".format(_span([r["seconds"] for r in rs]))
        if any(r["llm"] is not None for r in rs):
            line += "，LLM/题 {}".format(_span([r["llm"] for r in rs]))
        print(line)

        types = {}
        for r in rs:
            for typ, s in r["by_type"].items():
                types.setdefault(typ, []).append("{}/{}".format(s["pass"], s["n"]))
        if types:
            print("   " + "  ".join("{}: {}".format(t, "/".join(v))
                                    for t, v in types.items()))

    flips = _per_task(rows)
    if flips:
        print("\n===== 多次 run 之间结果翻转的任务 =====")
        print("（PASS/FAIL 随 run 变化，说明这些题不适合作为结论依据）")
        for agent, tid, pat in flips:
            print("  {:<7} {:<4} {}".format(agent, tid, pat))
    else:
        print("\n没有翻转任务：各次 run 逐条一致。")


if __name__ == "__main__":
    main()
