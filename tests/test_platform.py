# -*- coding: utf-8 -*-
"""数据中台 / 评测中台的集成测试（临时 SQLite，不调模型）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import datahub
import evalhub


def _use_tmp_db(monkeypatch, tmp_path):
    monkeypatch.setenv("MINGLI_PLATFORM_DB", str(tmp_path / "platform.sqlite3"))


def test_datahub_scan_registers_version_and_quality_gates(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    result = datahub.scan_and_store()

    assert result["chunks"] == 8681
    assert result["books"] == 45
    assert result["version"].startswith("ds-")
    assert result["assets"], "至少要登记 chunks / embeddings"

    checks = {c["check_name"]: c for c in datahub.checks_for(result["id"])}
    assert checks["embedding_alignment"]["status"] == "pass"
    assert checks["embedding_dim"]["status"] == "pass"
    assert checks["empty_text"]["status"] == "pass"

    latest = datahub.latest()
    assert latest["version"] == result["version"]
    assert latest["chunks"] == 8681


def test_evalhub_imports_existing_runs_and_gate_blocks_regression(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    datahub.scan_and_store()
    added, skipped, errors = evalhub.import_existing()

    assert added >= 10
    assert errors == []
    runs = evalhub.list_runs(limit=100)
    suites = {r["suite"] for r in runs}
    assert {"retrieval", "agent", "refusal"} <= suites

    by_source = {r["source"]: r for r in runs}
    tuned = by_source["results_8681_tuned.csv#rrf"]
    dense = by_source["results_v2.csv#dense"]
    multi = by_source["results_agent_multi.json"]
    single = by_source["results_agent_baseline.json"]

    # 检索掉 12.5 个点，回归门必须判失败
    bad = evalhub.compare(tuned["id"], dense["id"])
    assert bad["status"] == "fail"
    assert bad["gate_metric"] == "line_recall"

    # 多 Agent 比单 Agent 高 26.7 个点，必须通过
    good = evalhub.compare(single["id"], multi["id"])
    assert good["status"] == "pass"

    # 导入的历史结果没有数据集版本，不能冒充当前版本
    assert tuned["dataset_version"] == evalhub.IMPORTED_VERSION
    assert len(evalhub.cases_for(tuned["id"])) == 30
