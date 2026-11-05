# -*- coding: utf-8 -*-
"""评测中台的 MVP：登记 run、逐题明细、版本对比和回归门。

它不替代 eval/ 下已有的评测脚本，而是给那些脚本一个统一的账本：
- 之前的 results_agent_*.json / results_*.csv 可以一次性导入；
- 新跑一次检索评测会直接落库，带数据集版本和配置；
- 两次 run 可以并排比，掉点超过阈值就判回归失败。

指标口径保持和 eval/eval_matrics.py 一致：行号命中必须同书且行区间相交。
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

import agent_state
import corpus
from platform_db import connect

ROOT = Path(__file__).resolve().parent.parent
EVAL_DIR = ROOT / "eval"
QUESTIONS = EVAL_DIR / "questions.jsonl"
TOP_K = 5
STRATEGIES = ("dense", "bm25", "rrf")

GATE = {
    "retrieval": ("line_recall", 0.02),
    "agent": ("pass_rate", 0.05),
    "refusal": ("refusal_accuracy", 0.02),
    "feedback": ("pass_rate", 0.05),
}

IMPORTED_VERSION = "imported:unknown"
FEEDBACK_CASES = EVAL_DIR / "feedback_cases.jsonl"

METRIC_KEYS = {
    "retrieval": ("line_recall", "exact_recall", "line_mrr"),
    "agent": ("pass_rate", "auto_pass", "errors", "elapsed_seconds", "llm_mean"),
    "refusal": ("answered_rate", "refusal_accuracy", "invalid_outputs"),
    "feedback": ("pass_rate", "auto_pass", "auto_total", "human_review", "errors"),
}

# 判断“这次回答有没有改好”时，用字符二元组重合度做粗比较；
# 只用于线上反馈这种没有标准答案的场景，不能替代人工评测。
_REFUSAL_MARKERS = ("没有足够", "无法回答", "语料中没有")

# 相似度只要涨一点点就放行，等于把 LLM 的随机波动当成"修好了"。
# 0.02 是字符二元组 Jaccard 的经验值：几十个字的答案，涨 2 个点才不是噪声。
MIN_SIM_GAIN = float(os.environ.get("MINGLI_FEEDBACK_MIN_GAIN", "0.02"))


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _f(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _b(v):
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "1", "yes", "是")


def _mean(vals):
    vals = [v for v in vals if isinstance(v, (int, float))]
    return sum(vals) / len(vals) if vals else None


def _sha256(path):
    h = hashlib.sha256()
    h.update(Path(path).read_bytes())
    return h.hexdigest()


# ---------- 检索口径 ----------

def load_questions(path=QUESTIONS):
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def line_overlap(a, b):
    if not a or not b or a[0] is None or b[0] is None or a[0] != b[0]:
        return False
    return not (a[2] < b[1] or b[2] < a[1])


def chunk_spans(chunks=None):
    chunks = chunks or corpus.load_chunks()
    out = {}
    for c in chunks:
        m = c.get("meta") or {}
        out[c["chunk_id"]] = (m.get("sourcefile") or c.get("sourcefile"),
                              m.get("line_start"), m.get("line_end"))
    return out


def score_one(gold_ids, retrieved_ids, spans, top_k=TOP_K):
    golds = [g for g in (gold_ids or []) if g in spans]
    top = [cid for cid in (retrieved_ids or [])[:top_k] if cid in spans]
    if not golds:
        return None
    covered = [g for g in golds
               if any(line_overlap(spans[g], spans[cid]) for cid in top)]
    first = next((i + 1 for i, cid in enumerate(top)
                  if any(line_overlap(spans[g], spans[cid]) for g in golds)), None)
    return len(covered) / len(golds), (1.0 / first if first else 0.0)


# ---------- run 写入 ----------

def _insert_run(conn, name, source, suite, backend, dataset_version, config,
                metrics, status, notes, created_at, cases,
                state_version=None, benchmark_version=None, run_index=1,
                state_manifest=None):
    cur = conn.execute(
        "INSERT INTO eval_runs(name, source, suite, backend, dataset_version, config_json,"
        " metrics_json, status, notes, created_at, state_version, benchmark_version,"
        " run_index, state_manifest_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (name, source, suite, backend, dataset_version,
         json.dumps(config or {}, ensure_ascii=False),
         json.dumps(metrics or {}, ensure_ascii=False),
         status, notes, created_at, state_version, benchmark_version,
         run_index,
         json.dumps(state_manifest, ensure_ascii=False) if state_manifest else None),
    )
    run_id = cur.lastrowid
    for c in cases:
        conn.execute(
            "INSERT INTO eval_cases(run_id, case_id, question, answerable, category, output,"
            " can_answer, citations_json, recall, mrr, passed, latency_ms, detail_json,"
            " trace_id, llm_calls, prompt_tokens, completion_tokens, total_tokens)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, c.get("case_id"), c.get("question"),
             1 if c.get("answerable") else 0, c.get("category"), c.get("output"),
             None if c.get("can_answer") is None else (1 if c.get("can_answer") else 0),
             json.dumps(c.get("citations"), ensure_ascii=False) if c.get("citations") is not None else None,
             c.get("recall"), c.get("mrr"),
             None if c.get("passed") is None else (1 if c.get("passed") else 0),
             c.get("latency_ms"), json.dumps(c.get("detail"), ensure_ascii=False)
             if c.get("detail") is not None else None,
             c.get("trace_id"), c.get("llm_calls"),
             c.get("prompt_tokens"), c.get("completion_tokens"), c.get("total_tokens")),
        )
    return run_id


def _dataset_version(conn):
    row = conn.execute(
        "SELECT version FROM datasets ORDER BY scanned_at DESC, id DESC LIMIT 1"
    ).fetchone()
    return row["version"] if row else None


def run_retrieval(mode="rrf", top_k=TOP_K, limit=0, name=None, questions_path=QUESTIONS):
    """真跑一次检索评测并落库。首次调用会加载 BGE-M3，耗时主要在这里。"""
    from retrieval import retrieve_one

    questions = load_questions(questions_path)
    if limit:
        questions = questions[:limit]
    spans = chunk_spans()

    started = time.perf_counter()
    cases, line_recalls, exact_recalls, mrrs = [], [], [], []
    for q in questions:
        t0 = time.perf_counter()
        hits = retrieve_one(q["question"], top_k=top_k, mode=mode)
        ids = [h["chunk_id"] for h in hits]
        latency = (time.perf_counter() - t0) * 1000
        scored = score_one(q.get("gold_chunk_ids"), ids, spans, top_k)
        exact_hits = [g for g in (q.get("gold_chunk_ids") or []) if g in ids[:top_k]]
        exact_recall = len(exact_hits) / len(q.get("gold_chunk_ids") or [1]) if exact_hits else 0.0
        if scored is None:
            recall = mrr = None
        else:
            recall, mrr = scored
            if q.get("answerable"):
                line_recalls.append(recall)
                exact_recalls.append(exact_recall)
                mrrs.append(mrr)
        cases.append({
            "case_id": q["id"], "question": q["question"],
            "answerable": q.get("answerable"), "category": q.get("category"),
            "output": json.dumps(ids, ensure_ascii=False),
            "citations": ids, "recall": recall, "mrr": mrr,
            "passed": None if recall is None else recall > 0,
            "latency_ms": round(latency, 1),
            "detail": {"retrieved_chunk_ids": ids,
                       "gold_chunk_ids": q.get("gold_chunk_ids"),
                       "exact_recall": exact_recall},
        })

    metrics = {
        "line_recall": _mean(line_recalls),
        "exact_recall": _mean(exact_recalls),
        "line_mrr": _mean(mrrs),
        "n_answerable": len(line_recalls),
        "n_total": len(questions),
        "top_k": top_k,
        "mode": mode,
        "elapsed_seconds": round(time.perf_counter() - started, 1),
    }
    suite = "retrieval"
    with connect() as conn:
        version = _dataset_version(conn)
        run_id = _insert_run(
            conn,
            name or "retrieval/{}/top{}/{}".format(mode, top_k, _now()),
            None, suite, mode, version,
            {"mode": mode, "top_k": top_k, "limit": limit,
             "questions_sha256": _sha256(questions_path)},
            metrics, "done", None, _now(), cases,
        )
        conn.commit()
    return run_id


# ---------- 线上差评 → 回归用例 ----------

def load_feedback_cases(path=FEEDBACK_CASES):
    """读 eval/promote_feedback.py 生成的回归用例。"""
    path = Path(path)
    if not path.exists():
        return []
    out = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _norm_text(text):
    return re.sub(r"[\s\W_]+", "", str(text or "")).lower()


def _bigrams(text):
    text = _norm_text(text)
    if len(text) < 2:
        return {text} if text else set()
    return {text[i:i + 2] for i in range(len(text) - 1)}


def _similarity(a, b):
    """字符二元组 Jaccard；中文不需要分词，够用来判断“有没有往期望答案靠”。"""
    ba, bb = _bigrams(a), _bigrams(b)
    if not ba or not bb:
        return 0.0
    return len(ba & bb) / len(ba | bb)


def judge_feedback_case(case, result):
    """判断新回答是否修好了这条差评。

    能机器判的只有两类：
    1. 上次是拒答，这次必须答出来且带有效引用；
    2. 用户给了 expected_answer，新答案要比旧答案至少接近 ``MIN_SIM_GAIN``，
       且引用合规——只涨 0.002 这种幅度是随机波动，不算修好。
    其余返回 passed=None，交给人工，不混进 pass_rate。
    """
    answer = str(result.get("answer") or "")
    can_answer = result.get("can_answer")
    citations = result.get("citations_chunk_ids") or []
    valid_answer = (
        can_answer is True and bool(citations) and not result.get("invalid_output")
    )
    expected = str(case.get("expected_answer") or "").strip()
    bad_answer = str(case.get("bad_answer") or "")

    if case.get("bad_can_answer") is False:
        return {
            "passed": valid_answer,
            "auto": True,
            "reason": "上次拒答，这次要求给出带引用的回答"
            if not valid_answer else "已从拒答改为有依据的回答",
            "new_similarity": None,
            "old_similarity": None,
        }

    if expected:
        new_sim = _similarity(answer, expected)
        old_sim = _similarity(bad_answer, expected)
        if any(marker in expected for marker in _REFUSAL_MARKERS):
            passed = can_answer is False
            reason = "期望拒答，这次应保持拒答" if passed else "期望拒答，但这次仍在作答"
        else:
            gain = new_sim - old_sim
            passed = valid_answer and gain >= MIN_SIM_GAIN
            if passed:
                reason = "比旧答案更接近期望答案（+{:.3f}）".format(gain)
            elif valid_answer:
                reason = "只接近了 {:.3f}，低于噪声阈值 {:.2f}".format(
                    gain, MIN_SIM_GAIN
                )
            else:
                reason = "引用不合规，或没有比旧答案更接近期望答案"
        return {
            "passed": passed,
            "auto": True,
            "reason": reason,
            "new_similarity": round(new_sim, 4),
            "old_similarity": round(old_sim, 4),
        }

    return {
        "passed": None,
        "auto": False,
        "reason": "缺少 expected_answer，留给人看",
        "new_similarity": None,
        "old_similarity": None,
    }


def _run_feedback_case(case, mode=None):
    """按用例记录的模式重跑一次问答；没有记录就默认走 RAG。"""
    question = case["question"]
    mode = mode or case.get("mode") or "rag"
    if mode == "rag":
        from rag import answer
        return answer(question)
    if mode == "agent":
        from agent import agent_answer
        return agent_answer(question)
    if mode == "multi":
        from agent_multi import agent_answer
        return agent_answer(question)
    raise ValueError("未知 mode: {}".format(mode))


def run_feedback(mode=None, limit=0, name=None, cases_path=FEEDBACK_CASES):
    """重跑差评用例并登记成一个 suite=feedback 的 eval_run。

    和其他 suite 一样，用 evalhub.compare(baseline_id, new_id) 过回归门。
    """
    cases = load_feedback_cases(cases_path)
    if limit:
        cases = cases[:limit]
    if not cases:
        raise SystemExit(
            "没有反馈用例。先启动服务收集差评，再跑 eval/promote_feedback.py。"
        )

    started = time.perf_counter()
    rows, auto_passed, errors = [], 0, 0
    for case in cases:
        t0 = time.perf_counter()
        try:
            result = _run_feedback_case(case, mode=mode)
        except Exception as exc:  # 单条失败不拖垮整轮评测
            errors += 1
            result = {
                "answer": "", "can_answer": None, "citations_chunk_ids": [],
                "invalid_output": True, "error": str(exc),
            }
        latency = (time.perf_counter() - t0) * 1000
        judged = judge_feedback_case(case, result)
        if judged["passed"] is True:
            auto_passed += 1
        rows.append({
            "case_id": case.get("id"),
            "question": case.get("question"),
            "answerable": case.get("bad_can_answer") is not False,
            "category": "线上反馈",
            "output": result.get("answer"),
            "can_answer": result.get("can_answer"),
            "citations": result.get("citations_chunk_ids") or [],
            "recall": None, "mrr": None,
            "passed": judged["passed"],
            "latency_ms": round(latency, 1),
            "detail": {
                "judge": judged,
                "mode": mode or case.get("mode") or "rag",
                "reason": case.get("reason"),
                "expected_answer": case.get("expected_answer"),
                "bad_answer": case.get("bad_answer"),
                "refusal_reason": result.get("refusal_reason"),
                "error": result.get("error"),
            },
        })

    auto_total = sum(1 for r in rows if r["detail"]["judge"].get("auto"))
    metrics = {
        "pass_rate": (auto_passed / auto_total) if auto_total else None,
        "auto_pass": auto_passed,
        "auto_total": auto_total,
        "human_review": len(rows) - auto_total,
        "total": len(rows),
        "errors": errors,
        "elapsed_seconds": round(time.perf_counter() - started, 1),
    }
    suite = "feedback"
    backend = mode or "mixed"
    with connect() as conn:
        run_id = _insert_run(
            conn,
            name or "feedback/{}/{}".format(backend, _now()),
            None, suite, backend, _dataset_version(conn),
            {"cases": str(cases_path), "limit": limit,
             "cases_sha256": _sha256(cases_path) if Path(cases_path).exists() else None},
            metrics, "done", None, _now(), rows,
        )
        conn.commit()
    return run_id


# ---------- 导入历史结果 ----------

def _agent_case(t, tag=None):
    judge = t.get("judge") or {}
    passed = judge.get("auto_pass")
    usage = t.get("usage") or {}
    cid = t.get("id")
    return {
        "case_id": cid, "question": t.get("question"),
        "answerable": t.get("can_answer") is not False,
        "category": t.get("type"), "output": t.get("answer"),
        "can_answer": t.get("can_answer"), "citations": t.get("citations"),
        "passed": None if passed is None else bool(passed),
        "latency_ms": (t.get("seconds") or 0) * 1000,
        "detail": judge,
        # 分数 -> 轨迹 -> 成本：trace_id 是结果文件里的定位串（tag:case_id），
        # 不做成 UUID，是为了能直接从库跳回 eval/results_agent_<tag>.json 的那一条。
        "trace_id": "{}:{}".format(tag, cid) if tag else cid,
        "llm_calls": t.get("llm_calls"),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
    }


def _agent_metrics(data: dict) -> dict:
    """从结果文件（或内存里的同结构 dict）算出 run 级指标。"""
    s = data.get("summary") or {}
    tasks = data.get("tasks") or []
    total = s.get("total") or len(tasks)
    auto_pass = s.get("auto_pass")
    if auto_pass is None:
        auto_pass = sum(1 for t in tasks if (t.get("judge") or {}).get("auto_pass"))
    tokens = [((t.get("usage") or {}).get("total_tokens") or 0) for t in tasks]
    calls = [t.get("llm_calls") for t in tasks if isinstance(t.get("llm_calls"), int)]
    metrics = {
        "pass_rate": (auto_pass / total) if total else None,
        "auto_pass": auto_pass,
        "total": total,
        "errors": s.get("errors"),
        "elapsed_seconds": s.get("elapsed_seconds"),
        "llm_mean": (s.get("llm_calls") or {}).get("mean"),
        "by_type": s.get("by_type") or {},
        "benchmark_version": s.get("benchmark_version"),
        "state_version": s.get("state_version"),
        "run_index": s.get("run_index"),
    }
    if calls:
        metrics["llm_calls_total"] = sum(calls)
        # 每通过一题花掉多少次 LLM 调用：比「总分」更能说明多 Agent 的代价
        metrics["llm_calls_per_pass"] = round(sum(calls) / auto_pass, 2) if auto_pass else None
    if any(tokens):
        metrics["total_tokens"] = sum(tokens)
        metrics["tokens_per_pass"] = round(sum(tokens) / auto_pass, 1) if auto_pass else None
    return metrics


def _record(conn, data, source, *, state_version=None, benchmark_version=None,
            run_index=1, state_manifest=None, created_at=None, extra_config=None,
            backend=None, dataset_version=None):
    s = data.get("summary") or {}
    backend = s.get("agent") or backend or "single"
    config = {"tag": s.get("tag"), "source_file": source}
    config.update(extra_config or {})
    return _insert_run(
        conn, Path(source).stem if isinstance(source, str) else str(source),
        str(source), "agent", backend,
        dataset_version or _dataset_version(conn) or IMPORTED_VERSION,
        config, _agent_metrics(data), "done", None,
        created_at or datetime.now().isoformat(timespec="seconds"),
        [_agent_case(t, s.get("tag")) for t in (data.get("tasks") or [])],
        state_version=state_version or s.get("state_version"),
        benchmark_version=benchmark_version or s.get("benchmark_version"),
        run_index=run_index or s.get("run_index") or 1,
        state_manifest=state_manifest or s.get("state_manifest"),
    )


def record_agent_run(data: dict, source: str, *, state_version=None,
                     benchmark_version=None, run_index=1, state_manifest=None,
                     replace=True) -> int:
    """把一次 Agent 跑批直接记进账本（run_agent.py 结束时调用）。

    与 import_existing() 的区别：这里的数据是刚跑完的，不用等文件落盘再扫一遍。
    replace=True 时同一 source 覆盖旧记录，避免同一 tag 重跑后出现两条同名 run。
    """
    with connect() as conn:
        if replace:
            conn.execute("DELETE FROM eval_runs WHERE source=?", (str(source),))
        run_id = _record(conn, data, str(source),
                         state_version=state_version,
                         benchmark_version=benchmark_version,
                         run_index=run_index,
                         state_manifest=state_manifest)
        conn.commit()
    return run_id


def _import_agent(conn, path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    created = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    s = data.get("summary") or {}
    return _record(
        conn, data, path.name, created_at=created,
        state_version=s.get("state_version"),
        benchmark_version=s.get("benchmark_version"),
        run_index=s.get("run_index") or 1,
        state_manifest=s.get("state_manifest"),
        # 老结果文件不一定写 agent 字段，退回按文件名判断
        backend="multi" if "multi" in path.name else "single",
        # 导入的是历史结果，不知道它当时跑在哪版数据集上，不能冒充当前版本
        dataset_version=IMPORTED_VERSION,
    )


def _import_retrieval_csv(conn, path: Path):
    with path.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    created = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    version = IMPORTED_VERSION
    ids = []
    for strat in STRATEGIES:
        cases, recalls, exacts, mrrs = [], [], [], []
        for r in rows:
            answerable = _b(r.get("answerable"))
            recall = _f(r.get(f"{strat}_line_recall"), 0.0)
            exact = _f(r.get(f"{strat}_exact_recall"), 0.0)
            mrr = _f(r.get(f"{strat}_line_mrr"), 0.0)
            if answerable:
                recalls.append(recall)
                exacts.append(exact)
                mrrs.append(mrr)
            cases.append({
                "case_id": r.get("id"), "question": r.get("question"),
                "answerable": answerable, "category": r.get("category"),
                "output": r.get(f"{strat}_line_covered"),
                "recall": recall, "mrr": mrr,
                "passed": recall > 0, "latency_ms": None,
                "detail": {"covered": r.get(f"{strat}_line_covered"),
                           "exact_recall": exact},
            })
        metrics = {
            "line_recall": _mean(recalls), "exact_recall": _mean(exacts),
            "line_mrr": _mean(mrrs), "n_answerable": len(recalls),
            "n_total": len(rows), "top_k": TOP_K, "mode": strat,
        }
        ids.append(_insert_run(
            conn, "{}#{}".format(path.stem, strat), "{}#{}".format(path.name, strat),
            "retrieval", strat, version,
            {"source_file": path.name, "strategy": strat},
            metrics, "done", None, created, cases,
        ))
    return ids


def _import_refusal_csv(conn, path: Path):
    with path.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    ans = [r for r in rows if _b(r.get("answerable"))]
    unans = [r for r in rows if not _b(r.get("answerable"))]
    answered = sum(1 for r in ans if not _b(r.get("refused")))
    refused = sum(1 for r in unans if _b(r.get("refused")))
    metrics = {
        "answered_rate": answered / len(ans) if ans else None,
        "refusal_accuracy": refused / len(unans) if unans else None,
        "answered": answered, "answerable": len(ans),
        "refused_unanswerable": refused, "unanswerable": len(unans),
        "invalid_outputs": sum(1 for r in rows if _b(r.get("invalid_output"))),
        "n_total": len(rows),
    }
    cases = [{
        "case_id": r.get("id"), "question": r.get("question"),
        "answerable": _b(r.get("answerable")), "category": r.get("category"),
        "output": r.get("answer"), "can_answer": _b(r.get("can_answer")),
        "citations": json.loads(r.get("citations_chunk_ids") or "[]"),
        "passed": (not _b(r.get("refused"))) if _b(r.get("answerable"))
        else _b(r.get("refused")),
        "latency_ms": None,
        "detail": {"refused": _b(r.get("refused")),
                   "invalid_output": _b(r.get("invalid_output")),
                   "refusal_reason": r.get("refusal_reason")},
    } for r in rows]
    created = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    return _insert_run(
        conn, path.stem, path.name, "refusal", "rrf", IMPORTED_VERSION,
        {"source_file": path.name}, metrics, "done", None, created, cases,
    )


def import_existing(force=False):
    """把 eval/ 下已有的结果文件登记进库。返回 (新增, 跳过, 跳过原因)。"""
    added, skipped, errors = 0, 0, []
    with connect() as conn:
        for path in sorted(EVAL_DIR.glob("results_agent_*.json")):
            if path.name.endswith("_rescored.json"):
                continue
            exists = conn.execute("SELECT 1 FROM eval_runs WHERE source=?", (path.name,)).fetchone()
            if exists and not force:
                skipped += 1
                continue
            try:
                if force:
                    conn.execute("DELETE FROM eval_runs WHERE source=?", (path.name,))
                _import_agent(conn, path)
                added += 1
            except Exception as exc:  # 单个坏文件不该挡住其他文件
                errors.append("{}: {}".format(path.name, exc))
        for path in sorted(EVAL_DIR.glob("*results*.csv")):
            if "refusal" in path.name:
                sources = [path.name]
                importer = _import_refusal_csv
            else:
                sources = ["{}#{}".format(path.name, s) for s in STRATEGIES]
                importer = _import_retrieval_csv
            exists = [conn.execute("SELECT 1 FROM eval_runs WHERE source=?", (s,)).fetchone()
                      for s in sources]
            if all(exists) and not force:
                skipped += 1
                continue
            try:
                if force:
                    for s in sources:
                        conn.execute("DELETE FROM eval_runs WHERE source=?", (s,))
                importer(conn, path)
                added += 1
            except Exception as exc:
                errors.append("{}: {}".format(path.name, exc))
        conn.commit()
    return added, skipped, errors


# ---------- 查询 / 对比 ----------

def list_runs(suite=None, limit=100, conn=None):
    own = conn is None
    conn = conn or connect()
    try:
        sql = ("SELECT id, name, source, suite, backend, dataset_version, metrics_json,"
               " status, created_at FROM eval_runs")
        args = []
        if suite:
            sql += " WHERE suite=?"
            args.append(suite)
        sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
        args.append(limit)
        out = []
        for r in conn.execute(sql, args):
            d = dict(r)
            d["metrics"] = json.loads(d.pop("metrics_json") or "{}")
            out.append(d)
        return out
    finally:
        if own:
            conn.close()


def cases_for(run_id, conn=None):
    own = conn is None
    conn = conn or connect()
    try:
        out = []
        for r in conn.execute("SELECT * FROM eval_cases WHERE run_id=? ORDER BY id", (run_id,)):
            d = dict(r)
            for k in ("citations_json", "detail_json"):
                d[k.replace("_json", "")] = json.loads(d.pop(k) or "null")
            out.append(d)
        return out
    finally:
        if own:
            conn.close()


def compare(baseline_id, candidate_id, conn=None):
    own = conn is None
    conn = conn or connect()
    try:
        rows = conn.execute(
            "SELECT * FROM eval_runs WHERE id IN (?,?)", (baseline_id, candidate_id)
        ).fetchall()
        by_id = {r["id"]: r for r in rows}
        if len(by_id) != 2:
            return {"status": "invalid", "reason": "找不到 run", "checks": []}
        a, b = by_id[baseline_id], by_id[candidate_id]
        if a["suite"] != b["suite"]:
            return {"status": "invalid", "reason": "suite 不同，不能直接比", "checks": []}
        ma = json.loads(a["metrics_json"] or "{}")
        mb = json.loads(b["metrics_json"] or "{}")
        gate_key, threshold = GATE.get(a["suite"], (None, None))
        checks = []
        for key in METRIC_KEYS.get(a["suite"], ()):
            va, vb = ma.get(key), mb.get(key)
            if not isinstance(va, (int, float)) or not isinstance(vb, (int, float)):
                continue
            delta = vb - va
            status = "pass"
            if gate_key and key == gate_key and delta < -threshold:
                status = "fail"
            checks.append({
                "metric": key, "baseline": va, "candidate": vb,
                "delta": delta, "status": status,
            })
        gate = next((c for c in checks if c["metric"] == gate_key), None)
        status = "pass"
        if gate and gate["status"] == "fail":
            status = "fail"
        elif gate is None:
            status = "warn"

        # 归因信息：两条 run 的 Agent 状态、题目版本是否一致。
        # 不改变 pass/fail（避免历史 run 因为缺字段被一刀切判为不可比），只标注。
        state = {
            "baseline": a["state_version"],
            "candidate": b["state_version"],
            "benchmark_baseline": a["benchmark_version"],
            "benchmark_candidate": b["benchmark_version"],
        }
        state["same_state"] = bool(a["state_version"]) and a["state_version"] == b["state_version"]
        state["same_benchmark"] = a["benchmark_version"] == b["benchmark_version"]
        ma_manifest = json.loads(a["state_manifest_json"] or "null")
        mb_manifest = json.loads(b["state_manifest_json"] or "null")
        if ma_manifest and mb_manifest:
            state["diff"] = agent_state.diff(ma_manifest, mb_manifest)
        comparable = state["same_benchmark"] and (
            a["dataset_version"] == b["dataset_version"]
        )
        if not comparable:
            state["warning"] = "dataset 或 benchmark 版本不同，分数不可直接比较"

        return {
            "status": status,
            "suite": a["suite"],
            "baseline": {"id": a["id"], "name": a["name"]},
            "candidate": {"id": b["id"], "name": b["name"]},
            "gate_metric": gate_key,
            "threshold": threshold,
            "checks": checks,
            "comparable": comparable,
            "state": state,
        }
    finally:
        if own:
            conn.close()


# ---------- 多次运行：case 矩阵与接受规则 ----------

def case_matrix(run_ids, conn=None):
    """把同一实验的多次 run 对齐成 case × run 矩阵。

    单次分数回答「这次过了几题」，矩阵回答另外两个问题：
    - 哪些题是稳定过的（每次都对），哪些是抽签过的（flip）；
    - 改动之后翻转的是哪几条，而不是只有一个总分。

    只统计 passed 不为 NULL 的记录；如果某次 run 只跑了部分题（--limit），
    那个 case 的 total 会小于 run 数，标 partial=True。
    """
    ids = [int(x) for x in run_ids]
    if not ids:
        return {"runs": [], "cases": [], "summary": {"n_runs": 0, "n_cases": 0}}
    own = conn is None
    conn = conn or connect()
    try:
        marks = ",".join("?" for _ in ids)
        rows = conn.execute(
            "SELECT run_id, case_id, passed FROM eval_cases"
            " WHERE run_id IN ({}) AND case_id IS NOT NULL ORDER BY run_id, id".format(marks),
            ids,
        ).fetchall()
        order, by_case = [], {}
        for r in rows:
            if r["passed"] is None:
                continue
            cid = r["case_id"]
            if cid not in by_case:
                by_case[cid] = []
                order.append(cid)
            by_case[cid].append(bool(r["passed"]))

        cases = []
        for cid in order:
            vals = by_case[cid]
            passes, total = sum(vals), len(vals)
            cases.append({
                "case_id": cid,
                "runs": vals,
                "passes": passes,
                "total": total,
                "flip": 0 < passes < total,
                "stable_pass": passes == total,
                "partial": total < len(ids),
            })

        n = len(cases)
        flips = sum(1 for c in cases if c["flip"])
        stable = sum(1 for c in cases if c["stable_pass"])
        summary = {
            "n_runs": len(ids), "n_cases": n,
            "flip": flips, "flip_rate": round(flips / n, 3) if n else None,
            "stable_pass": stable,
            "stable_pass_rate": round(stable / n, 3) if n else None,
            "mean_pass_rate": round(sum(c["passes"] for c in cases)
                                    / max(1, sum(c["total"] for c in cases)), 3),
            "partial_cases": sum(1 for c in cases if c["partial"]),
        }
        return {"runs": ids, "cases": cases, "summary": summary}
    finally:
        if own:
            conn.close()


def _decide(reference: list[float | None], candidate: list[float | None], n_cases: int,
            threshold: float, min_gain_cases: float = 1.0) -> dict:
    """纯函数：给定基准与候选各次 run 的主指标，判断是否接受候选。

    为什么不直接照搬「候选分数 > 基准分数就接受」：15 题里 1 题就是 6.7 个点，
    单次高 1 题可能只是模型波动。这里用两种证据：

      区间不重叠（候选最差 > 基准最好）——强证据，直接接受；
      均值涨够（换算成题数 >= min_gain_cases）——弱证据，接受但标注；
      候选最差比基准均值还低超过阈值——回归，拒绝；
      其余——inconclusive，不当作改进，也不当作退步。

    reference / candidate 是同一实验里各次 run 的主指标（0~1）。
    """
    ref = [float(x) for x in reference if x is not None]
    cand = [float(x) for x in candidate if x is not None]
    if not ref or not cand:
        return {"decision": "invalid", "reason": "缺少可比较的指标", "reference": ref,
                "candidate": cand}
    ref_mean = sum(ref) / len(ref)
    cand_mean = sum(cand) / len(cand)
    ref_max, ref_min = max(ref), min(ref)
    cand_max, cand_min = max(cand), min(cand)
    gain = cand_mean - ref_mean
    gain_cases = gain * max(1, int(n_cases))

    if cand_min < ref_mean - threshold:
        decision, strength = "reject", "regression"
        reason = "候选最差 {:.3f} 低于基准均值 {:.3f} 超过阈值 {:.2f}".format(
            cand_min, ref_mean, threshold)
    elif cand_min > ref_max:
        decision, strength = "accept", "interval"
        reason = "候选最差 {:.3f} 高于基准最好 {:.3f}，区间不重叠".format(cand_min, ref_max)
    elif gain_cases >= min_gain_cases:
        decision, strength = "accept", "mean"
        reason = "均值涨 {:.1f} 题（阈值 {:.1f} 题），但区间仍重叠".format(
            gain_cases, min_gain_cases)
    else:
        decision, strength = "inconclusive", None
        reason = "均值只涨 {:.1f} 题，低于 {:.1f} 题的噪声阈值".format(
            gain_cases, min_gain_cases)

    return {
        "decision": decision, "strength": strength, "reason": reason,
        "reference": {"runs": ref, "mean": round(ref_mean, 4),
                      "min": ref_min, "max": ref_max},
        "candidate": {"runs": cand, "mean": round(cand_mean, 4),
                      "min": cand_min, "max": cand_max},
        "gain": round(gain, 4), "gain_cases": round(gain_cases, 2),
        "threshold": threshold, "min_gain_cases": min_gain_cases,
    }


def accept_candidate(reference_run_ids, candidate_run_ids, suite="agent",
                     min_gain_cases=1.0, conn=None):
    """从账本里取两次实验的指标，判断候选是否可以被接受。

    用法::

        evalhub.accept_candidate([12, 13, 14], [15, 16, 17])

    返回 decision = accept / reject / inconclusive，同时给出两组 run 的原始指标，
    便于把判断依据一起贴进 round 记录。
    """
    own = conn is None
    conn = conn or connect()
    try:
        def load(ids):
            out = []
            for rid in ids:
                row = conn.execute(
                    "SELECT * FROM eval_runs WHERE id=?", (int(rid),)).fetchone()
                if row is None:
                    continue
                out.append({"id": row["id"], "name": row["name"],
                            "metrics": json.loads(row["metrics_json"] or "{}")})
            return out

        ref_runs, cand_runs = load(reference_run_ids), load(candidate_run_ids)
        key, threshold = GATE.get(suite, ("pass_rate", 0.0))
        ref_vals = [r["metrics"].get(key) for r in ref_runs]
        cand_vals = [r["metrics"].get(key) for r in cand_runs]
        n_cases = max([int(r["metrics"].get("total") or 0) for r in ref_runs + cand_runs] or [0])
        result = _decide(ref_vals, cand_vals, n_cases, threshold, min_gain_cases)
        result.update({"suite": suite, "metric": key,
                       "reference_runs": ref_runs, "candidate_runs": cand_runs,
                       "n_cases": n_cases})
        return result
    finally:
        if own:
            conn.close()


if __name__ == "__main__":
    import io
    import sys

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    added, skipped, errors = import_existing()
    print("导入 %d 个结果文件，跳过 %d 个" % (added, skipped))
    for e in errors:
        print("  !", e)
    for r in list_runs(limit=30):
        print("%3d  %-10s %-34s %s" % (r["id"], r["suite"], r["name"], r["metrics"]))
