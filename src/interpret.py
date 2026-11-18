# -*- coding: utf-8 -*-
"""解读层：给引用片段配一段现代汉语释义。

边界先说清楚：**译文是辅助阅读，不是证据。** 它不进引用链、不参与
「原文是否支持这句话」的判断，前端也必须在界面上标明这一点。换句话说，
引用的可信度仍然只由原文和 chunk_id 决定，译文只是帮读者把原文读顺。

缓存按原文内容哈希（不含 chunk_id），append-only JSONL：
同一段原文被不同回答引用时只翻一次；改了提示词就 bump `CACHE_VERSION`，
旧译文自然失效，不用清理文件。
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Any

import rag

# prompt 或输出格式变了就 +1，旧缓存自动失效。
CACHE_VERSION = "v1"
# 单段最多送这么多字；超出的部分不翻，接口用 truncated 标出来。
MAX_CHARS = 1500

_DEFAULT_CACHE = Path(__file__).resolve().parent.parent / "data" / "interpret_cache.jsonl"

INTERPRET_PROMPT = """你在做古籍阅读的「白话释义」，不是问答，也不是算命。

任务：把用户给出的古籍原文逐句译成现代汉语，帮助读者读懂字面意思。

规则：
1. 只做对译，不增不减：原文没有的背景、典故、评价、建议一律不加。
2. 保留专名：书名、人名、术语（如「正官」「食神」「月令」）原样保留，
   必要时在括号里给最短的字面解释。
3. 不做吉凶判断、不预测、不建议：不要出现「你会」「有利于」「应当」这类
   把原文变成结论的话。
4. 不做现代类比：不要用股票、职场、婚姻等现代生活场景解释古代概念。
5. 原文有残缺、异体字或明显错字时，按上下文直译，必要时在译文末尾用
   「（原文此处残缺）」标出。
6. 译文只是辅助阅读，不构成引用依据；不要在译文里加引用编号。

只输出 JSON，不要输出 JSON 以外的任何文字。JSON 格式：
{"translation": "白话译文"}

整段无法成句翻译（例如只有目录、乱码）时，translation 返回空字符串。
"""

_CACHE: dict[str, str] = {}
_LOADED_PATH: Path | None = None
_LOCK = threading.Lock()


def cache_path() -> Path:
    raw = (os.environ.get("MINGLI_INTERPRET_CACHE") or "").strip()
    return Path(raw) if raw else _DEFAULT_CACHE


def _key(text: str) -> str:
    # 版本和截断长度都进 key：改规则或改上限后不会读到旧口径的译文。
    payload = "{}:{}:{}".format(CACHE_VERSION, MAX_CHARS, text)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _ensure_loaded(path: Path) -> None:
    global _CACHE, _LOADED_PATH
    if _LOADED_PATH == path:
        return
    with _LOCK:
        if _LOADED_PATH == path:
            return
        cache: dict[str, str] = {}
        try:
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue  # 半行（进程被杀）直接跳过，不让整份缓存作废
                    key = row.get("key")
                    translation = row.get("translation")
                    if isinstance(key, str) and isinstance(translation, str) and translation:
                        cache[key] = translation
        except FileNotFoundError:
            pass
        _CACHE = cache
        _LOADED_PATH = path


def _store(path: Path, key: str, chunk_id: int, translation: str) -> None:
    row = {
        "key": key,
        "chunk_id": chunk_id,
        "version": CACHE_VERSION,
        "translation": translation,
    }
    # 只存译文和溯源字段；key、请求头、访客 id 都不落盘。
    with _LOCK:
        _CACHE[key] = translation
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError:
            # 写盘失败不影响这次返回；下次 miss 再翻一遍即可。
            pass


def prepare(chunks: list[dict[str, Any]], force: bool = False) -> tuple[list[dict], list[tuple[dict, str, str]]]:
    """把请求拆成「已命中缓存」和「要调模型」两部分。

    返回 (items, misses)：items 与输入同序，可直接回给前端；
    misses 是 [(item, 送入模型的原文, 缓存 key)]，由调用方决定何时占闸门/扣额度。
    key 按完整原文算，送入模型的可能被截断——这样下次同一段仍然命中。
    """
    path = cache_path()
    _ensure_loaded(path)
    items: list[dict[str, Any]] = []
    misses: list[tuple[dict[str, Any], str, str]] = []
    for chunk in chunks:
        text = str(chunk.get("text") or "").strip()
        item = {
            "chunk_id": int(chunk["chunk_id"]),
            "translation": None,
            "cached": False,
            "truncated": len(text) > MAX_CHARS,
            "error": None,
        }
        items.append(item)
        if not text:
            item["error"] = "原文为空"
            continue
        key = _key(text)
        hit = None if force else _CACHE.get(key)
        if hit:
            item["translation"] = hit
            item["cached"] = True
            continue
        misses.append((item, text[:MAX_CHARS], key))
    return items, misses


def fill(items: list[dict[str, Any]], misses: list[tuple[dict, str, str]],
         api_key: str | None = None) -> None:
    """逐条补译文。单条失败只记在那一项上，不拖垮整批。"""
    path = cache_path()
    for item, text, key in misses:
        try:
            translation = translate(text, api_key=api_key)
        except Exception as exc:  # noqa: BLE001 - 一条失败不该让整组引用都不可读
            item["error"] = "释义生成失败：{}".format(str(exc)[:160])
            continue
        if not translation:
            item["error"] = "这段原文无法成句对译"
            continue
        item["translation"] = translation
        _store(path, key, item["chunk_id"], translation)


def translate(text: str, api_key: str | None = None) -> str:
    """调一次模型，返回白话译文。空串表示原文无法成句翻译。"""
    messages = [
        {"role": "system", "content": INTERPRET_PROMPT},
        {"role": "user", "content": "【原文】\n{}".format(text)},
    ]
    raw = rag._chat(messages, api_key=api_key)
    data = rag._parse_json(raw)
    translation = data.get("translation")
    if not isinstance(translation, str):
        raise ValueError("模型没有返回 translation 字段")
    translation = translation.strip()
    if not translation:
        return ""
    # 粗校验：译文长度明显超过原文时，多半是模型在讲解而不是对译。
    if len(translation) > max(600, len(text) * 4):
        raise ValueError("译文长度异常（{} 字 → {} 字）".format(len(text), len(translation)))
    return translation


def stats() -> dict[str, Any]:
    return {"cache_version": CACHE_VERSION, "cache_size": len(_CACHE),
            "max_chars": MAX_CHARS}
