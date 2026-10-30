# -*- coding: utf-8 -*-
"""统一的语料读取与编号规则。

标点组（punct.jsonl）先读，保持 1..N 的原编号——eval/questions.jsonl 里的
gold_chunk_ids 依赖这套编号；无标点组（unpunct.jsonl）随后读，从 N+1 顺延。

编号规则只有这一份，embed / retrieval / eval 都调这里。以前三处各读各的文件，
入库无标点组时很容易出现"embedding 是一套顺序、检索是另一套顺序"，而症状是
检索结果看起来正常、分数悄悄变差。改动这里的顺序或编号会让
data/embeddings.npy 与 eval 结果全部失效，必须重跑 src/embed.py。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

# 顺序即编号：先标点组（保持原编号），再无标点组。
CORPUS_FILES = (("punct.jsonl", "punct"), ("unpunct.jsonl", "unpunct"))

REQUIRED_FIELDS = ("sourcefile", "chunk_text", "meta")


def data_dir() -> Path:
    """默认 <repo>/data，可用 MINGLI_DATA_DIR 覆盖（部署到别的目录时用）。"""
    return Path(
        os.environ.get("MINGLI_DATA_DIR", Path(__file__).resolve().parent.parent / "data")
    )


def iter_chunks(dd: Path | None = None):
    """按固定顺序产出 chunk，并把 chunk_id 重编为全局连续编号。"""
    dd = Path(dd) if dd else data_dir()
    next_id = 1
    for filename, source in CORPUS_FILES:
        path = dd / "chunks" / filename
        if not path.exists():
            raise FileNotFoundError(f"缺少语料文件：{path}")
        with path.open("r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{lineno} 不是合法 JSON：{exc}") from exc
                rec["chunk_id"] = next_id
                rec.setdefault("meta", {})["index_source"] = source
                next_id += 1
                yield rec


def load_chunks(dd: Path | None = None) -> list[dict]:
    return list(iter_chunks(dd))
