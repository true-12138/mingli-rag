# -*- coding: utf-8 -*-
"""冻结 Benchmark：题面与判据分离、sha256 可校验、dev/holdout 不重叠。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "eval"))

import benchmark


def test_frozen_benchmark_matches_its_sha256():
    result = benchmark.verify()
    assert result["frozen"] is True
    assert result["ok"] is True, result.get("error")
    assert result["status"] == "frozen"


def test_splits_are_disjoint_and_cover_every_case():
    index = benchmark.load_index()
    dev = set(index["dev_cases"])
    holdout = set(index["holdout_cases"])

    assert dev.isdisjoint(holdout)
    assert len(dev) == 10
    assert len(holdout) == 5
    assert {c["id"] for c in benchmark.load_cases()} == dev | holdout


def test_public_cases_do_not_leak_the_rubric():
    for case in benchmark.load_cases():
        for private_field in ("required_tools", "evidence_books", "pass_criteria"):
            assert private_field not in case, "{} 泄露了 {}".format(case["id"], private_field)


def test_merged_tasks_carry_private_rubric():
    tasks = {t["id"]: t for t in benchmark.load_tasks(split="holdout")}

    assert set(tasks) == {"a03", "a05", "b05", "c02", "d02"}
    for task in tasks.values():
        assert "question" in task
        assert isinstance(task["required_tools"], list)
        assert isinstance(task["pass_criteria"], list)
    assert tasks["a03"]["required_tools"], "a03 应该带必需工具判据"


def test_gold_files_are_parseable_and_match_case_ids():
    index = benchmark.load_index()
    for case_id in list(index["dev_cases"]) + list(index["holdout_cases"]):
        gold = benchmark.load_gold(case_id)
        assert gold["id"] == case_id
