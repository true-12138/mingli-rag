# -*- coding: utf-8 -*-
"""Agent State：把「提示词 + 运行参数」当成一个可版本化的整体。

为什么需要它：一次评测的分数如果不带状态版本，就只能说明「某个时间点跑出 12.7」，
不能说明「是哪一版提示词跑出的 12.7」。改了三个 prompt 之后分数涨了，也说不清
是哪一处改动带来的。这里给每次 run 记一个 `state_version`，回答两个问题：

    这次 run 用的是哪版 Agent？
    两次 run 之间，到底改了哪几个文件？

版本 = 所有提示词文件与 agent_config.json 的内容哈希。只改文件、不改语义也会变，
这是有意的：宁可多记一次，也不要在需要归因时发现版本相同。

提示词放在 `src/prompts/*.md`，不放在 Python 常量里。好处是：
- diff 时看到的是自然语言，不是转义过的字符串；
- 做 A/B 时只改文件，不改代码，回滚就是一次 git checkout；
- 评测脚本可以只依赖本模块拿到版本，不必 import agent（也就不会加载 BGE-M3）。

新增一个会进入模型上下文的提示词时，必须同时在 PROMPT_FILES 里登记，
否则它的改动不会让 state_version 变化。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "agent_config.json"

# 名字 -> 文件名。名字用于代码里引用，文件名允许以后改而不用动调用方。
PROMPT_FILES = {
    "rag_system": "rag_system.md",
    "rewriter": "rewriter.md",
    "single_system": "single_system.md",
    "planner": "planner.md",
    "retriever": "retriever.md",
    "verifier": "verifier.md",
    "synthesizer": "synthesizer.md",
}

# agent_config.json 缺字段时的兜底；改这里等价于改配置，因此也会进入版本。
CONFIG_DEFAULTS: dict[str, Any] = {
    "max_steps": 6,
    "evidence_char": 420,
    "retriever_max_calls": 2,
    "history_turns": 3,
    "history_chars": 1200,
    "answer_top_k": 5,
}


def _read_text(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(
            "找不到 Agent State 文件：{}\n"
            "提示词应从 src/prompts/ 读取；缺文件时不要静默回退到内置字符串，"
            "否则版本号会与实际生效的提示词不一致。".format(path)
        )
    return path.read_text(encoding="utf-8")


def load_prompt(name: str, prompt_dir: Path | str | None = None) -> str:
    """按名字读一个提示词。

    原样返回，不做 strip：文件末尾的换行也是提示词的一部分，改了它 state_version
    就会变——这正是「版本必须等于实际生效内容」的意思。
    """
    if name not in PROMPT_FILES:
        raise KeyError("未登记的提示词：{}（先加到 PROMPT_FILES）".format(name))
    base = Path(prompt_dir) if prompt_dir else DEFAULT_PROMPT_DIR
    return _read_text(base / PROMPT_FILES[name])


def load_config(config_path: Path | str | None = None) -> dict[str, Any]:
    """读运行参数；文件里没有的键用 CONFIG_DEFAULTS 补齐。"""
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    data: dict[str, Any] = {}
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    merged = dict(CONFIG_DEFAULTS)
    merged.update({k: v for k, v in data.items() if not k.startswith("_")})
    return merged


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def manifest(prompt_dir: Path | str | None = None,
             config_path: Path | str | None = None) -> dict[str, Any]:
    """返回可直接写进 run 的 state 清单。

    结构：
        {"version": "<64 位 hex>",
         "files": {"prompts/planner.md": "<sha>", ...},
         "config": {...}}

    version 覆盖 files 与 config 的规范化 JSON，因此改提示词或改参数都会变。
    """
    base = Path(prompt_dir) if prompt_dir else DEFAULT_PROMPT_DIR
    files: dict[str, str] = {}
    for name in sorted(PROMPT_FILES):
        text = _read_text(base / PROMPT_FILES[name])
        # 用「名字 + 内容」而不是直接用文件，避免文件名改动被当成状态未变
        files["prompts/" + PROMPT_FILES[name]] = _sha256_bytes(
            (name + "\0" + text).encode("utf-8")
        )
    cfg = load_config(config_path)
    payload = json.dumps({"files": files, "config": cfg},
                         ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {"version": _sha256_bytes(payload.encode("utf-8")), "files": files, "config": cfg}


def state_version(prompt_dir: Path | str | None = None,
                  config_path: Path | str | None = None) -> str:
    return manifest(prompt_dir, config_path)["version"]


def short(version: str | None, n: int = 12) -> str:
    """展示用短版本。只用于打印，库里存完整值。"""
    if not version:
        return "unknown"
    return version[:n]


def diff(old: dict[str, Any] | None, new: dict[str, Any] | None) -> dict[str, Any]:
    """比较两份 manifest，给出「哪几个文件变了」。

    只拿到版本字符串时无法归因；所以 run 里最好把 manifest 的 files 一起存下来。
    """
    old = old or {}
    new = new or {}
    a = old.get("files") or {}
    b = new.get("files") or {}
    changed = sorted(k for k in a.keys() & b.keys() if a[k] != b[k])
    added = sorted(b.keys() - a.keys())
    removed = sorted(a.keys() - b.keys())
    ca, cb = old.get("config") or {}, new.get("config") or {}
    config_changed = sorted(k for k in ca.keys() | cb.keys() if ca.get(k) != cb.get(k))
    return {
        "same": not (changed or added or removed or config_changed),
        "changed_files": changed,
        "added_files": added,
        "removed_files": removed,
        "config_changed": config_changed,
    }


def describe(prompt_dir: Path | str | None = None,
             config_path: Path | str | None = None) -> str:
    """终端里一眼能看懂的摘要，run 开始时打印一行。"""
    m = manifest(prompt_dir, config_path)
    return "state {} · {} 个提示词 · max_steps={}".format(
        short(m["version"]), len(m["files"]), m["config"].get("max_steps"))


if __name__ == "__main__":
    import io
    import sys

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    m = manifest()
    print("state_version:", m["version"])
    for path, sha in m["files"].items():
        print("  {:32} {}".format(path, sha[:12]))
    print("config:", json.dumps(m["config"], ensure_ascii=False))
