# -*- coding: utf-8 -*-
"""P50/P95 与成本估算的离线测试。"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval"))

import report_cost as rc  # noqa: E402


def test_percentile_uses_nearest_rank():
    values = [5.0, 1.0, 4.0, 2.0, 3.0]
    assert rc.percentile(values, 50) == 3.0
    assert rc.percentile(values, 95) == 5.0
    assert rc.percentile([], 50) is None


def test_estimate_cost_splits_cached_prompt():
    # miss 800k * 1 + cached 200k * 0.1 + completion 500k * 2 = 1.82
    got = rc.estimate_cost(1_000_000, 200_000, 500_000, 1.0, 0.1, 2.0)
    assert got == 1.82


def test_estimate_cost_returns_none_without_prices():
    assert rc.estimate_cost(1000, 100, 500, None, None, 1.0) is None
    assert rc.estimate_cost(1000, 100, 500, 1.0, None, None) is None


def test_summarize_and_build_report():
    rows = [
        {"tag": "t", "agent": "single", "seconds": 1.0, "passed": True, "llm_calls": 2,
         "prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500,
         "cached_tokens": 200},
        {"tag": "t", "agent": "single", "seconds": 3.0, "passed": False, "llm_calls": 4,
         "prompt_tokens": 3000, "completion_tokens": 1500, "total_tokens": 4500,
         "cached_tokens": 0},
    ]
    report = rc.build_report(rows, None, {"input": 1.0, "cached_input": 0.1, "output": 2.0})
    o = report["overall"]
    assert o["n"] == 2 and o["passed"] == 1
    assert o["p50_seconds"] == 1.0 and o["p95_seconds"] == 3.0
    assert o["prompt_tokens"] == 4000 and o["completion_tokens"] == 2000
    assert o["cost"] == 0.00782
    assert report["by_tag"][0]["tag"] == "t (single)"
    assert "合计" in rc.render(report)


def test_load_results_reads_usage(tmp_path):
    path = tmp_path / "results_agent_x.json"
    path.write_text(json.dumps({
        "summary": {"tag": "x", "agent": "multi"},
        "tasks": [{
            "id": "a01", "seconds": 2.5, "llm_calls": 3,
            "usage": {"prompt_tokens": 100, "completion_tokens": 50,
                      "total_tokens": 150, "cached_tokens": 10},
            "judge": {"auto_pass": True},
        }],
    }), encoding="utf-8")
    rows = rc.load_results([path])
    assert len(rows) == 1
    assert rows[0]["tag"] == "x" and rows[0]["agent"] == "multi"
    assert rows[0]["prompt_tokens"] == 100 and rows[0]["passed"] is True


def test_load_db_and_elapsed_ms_scale(tmp_path):
    db = tmp_path / "app.sqlite3"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE runs (elapsed_ms REAL, llm_calls INT, prompt_tokens INT, "
        "completion_tokens INT, total_tokens INT, cost_usd REAL, status TEXT)")
    conn.execute("INSERT INTO runs VALUES (1000, 2, 10, 5, 15, 0, 'succeeded')")
    conn.execute("INSERT INTO runs VALUES (3000, 4, 20, 10, 30, 0, 'refused')")
    conn.commit()
    conn.close()

    rows = rc.load_db(db)
    assert rows and len(rows) == 2
    report = rc.build_report([], rows, {"input": None, "cached_input": None, "output": None})
    db_sum = report["db"]
    assert db_sum["n"] == 2
    assert db_sum["p50_seconds"] == 1.0 and db_sum["p95_seconds"] == 3.0
    assert db_sum["status"] == {"succeeded": 1, "refused": 1}
    assert db_sum["stored_cost"] == 0.0
