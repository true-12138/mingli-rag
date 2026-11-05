# -*- coding: utf-8 -*-
"""评测归因：case × run 矩阵、接受规则、旧库补列。"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import platform_db


def _use_tmp_db(monkeypatch, tmp_path):
    monkeypatch.setenv("MINGLI_PLATFORM_DB", str(tmp_path / "platform.sqlite3"))


def _insert_run(conn, source, metrics, cases):
    import evalhub

    return evalhub._insert_run(
        conn, source, source, "agent", "single", None, {}, metrics,
        "done", None, "2026-11-05T00:00:00",
        [{"case_id": cid, "passed": passed} for cid, passed in cases],
    )


# ---------- 纯函数：接受规则 ----------

def test_interval_separation_is_a_strong_accept():
    import evalhub

    result = evalhub._decide([0.50, 0.53, 0.47], [0.80, 0.87, 0.80], n_cases=15, threshold=0.05)

    assert result["decision"] == "accept"
    assert result["strength"] == "interval"
    assert result["candidate"]["min"] > result["reference"]["max"]


def test_small_mean_gain_is_inconclusive_not_an_improvement():
    import evalhub

    # 15 题里均值涨 0.5 题：落在噪声里，不能当成改进
    result = evalhub._decide([0.533], [0.567], n_cases=15, threshold=0.05)

    assert result["decision"] == "inconclusive"
    assert result["gain_cases"] < 1.0


def test_regression_is_rejected():
    import evalhub

    result = evalhub._decide([0.80, 0.80], [0.60, 0.87], n_cases=15, threshold=0.05)

    assert result["decision"] == "reject"
    assert result["strength"] == "regression"


def test_missing_metrics_are_invalid():
    import evalhub

    assert evalhub._decide([None], [None], n_cases=15, threshold=0.05)["decision"] == "invalid"


# ---------- case × run 矩阵 ----------

def test_case_matrix_finds_flips_and_stable_passes(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    import evalhub

    with platform_db.connect() as conn:
        _insert_run(conn, "r1", {"pass_rate": 0.667},
                    [("a", True), ("b", False), ("c", True)])
        _insert_run(conn, "r2", {"pass_rate": 0.333},
                    [("a", True), ("b", False), ("c", False)])
        conn.commit()
        run_ids = [r["id"] for r in conn.execute("SELECT id FROM eval_runs ORDER BY id")]

    matrix = evalhub.case_matrix(run_ids)
    by_case = {c["case_id"]: c for c in matrix["cases"]}

    assert by_case["a"]["stable_pass"] is True and by_case["a"]["flip"] is False
    assert by_case["b"]["stable_pass"] is False and by_case["b"]["flip"] is False
    assert by_case["c"]["flip"] is True and by_case["c"]["passes"] == 1
    assert matrix["summary"]["n_cases"] == 3
    assert matrix["summary"]["flip"] == 1
    assert matrix["summary"]["stable_pass"] == 1


def test_case_matrix_marks_partial_runs(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    import evalhub

    with platform_db.connect() as conn:
        _insert_run(conn, "full", {"pass_rate": 1.0}, [("a", True), ("b", True)])
        _insert_run(conn, "limited", {"pass_rate": 1.0}, [("a", True)])
        conn.commit()
        run_ids = [r["id"] for r in conn.execute("SELECT id FROM eval_runs ORDER BY id")]

    matrix = evalhub.case_matrix(run_ids)
    by_case = {c["case_id"]: c for c in matrix["cases"]}

    assert by_case["a"]["total"] == 2 and by_case["a"]["partial"] is False
    assert by_case["b"]["total"] == 1 and by_case["b"]["partial"] is True
    assert matrix["summary"]["partial_cases"] == 1


# ---------- 旧库补列 ----------

def test_connect_migrates_an_old_database(tmp_path, monkeypatch):
    db = tmp_path / "old.sqlite3"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE eval_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT);
        CREATE TABLE eval_cases (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER);
        """
    )
    conn.commit()
    conn.close()

    monkeypatch.setenv("MINGLI_PLATFORM_DB", str(db))
    with platform_db.connect() as fresh:
        run_cols = {row[1] for row in fresh.execute("PRAGMA table_info(eval_runs)")}
        case_cols = {row[1] for row in fresh.execute("PRAGMA table_info(eval_cases)")}

    assert {"state_version", "benchmark_version", "run_index"} <= run_cols
    assert {"llm_calls", "total_tokens", "trace_id"} <= case_cols
