# -*- coding: utf-8 -*-
"""检索运行时的并发边界：模型只能加载一次。

冷启动时多个用户同时发问，如果没有锁，每个线程都会加载一份 BGE-M3。
在 2C4G 的机器上这不是慢一点，是直接 OOM。
"""
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import retrieval


def test_lazy_model_loads_once_under_concurrency(monkeypatch):
    calls = []
    gate = threading.Event()

    def slow_load(self):
        calls.append(1)
        gate.wait(timeout=2)  # 让其他线程有机会同时进入 _load
        time.sleep(0.01)
        self._m = object()
        return self._m

    monkeypatch.setattr(retrieval._LazyModel, "_load_locked", slow_load)
    model = retrieval._LazyModel("fake-model")

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(model._load) for _ in range(8)]
        time.sleep(0.05)  # 等第一个线程进入并占住锁
        gate.set()
        loaded = [f.result(timeout=5) for f in futures]

    assert len(calls) == 1, "并发冷启动时模型被加载了 {} 次".format(len(calls))
    assert all(item is loaded[0] for item in loaded)
