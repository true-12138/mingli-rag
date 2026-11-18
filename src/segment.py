# -*- coding: utf-8 -*-
"""自动断句：给无标点古籍补上句读，让读者能一段一段读。

边界先说清楚：**这是阅读辅助，不是校勘。**

- 只允许「插入标点」，不允许改字。每一段模型输出都要去掉标点与空白后与原文
  逐字比对，多一字、少一字、换一个异体字都判失败，宁可这段不断句。
- 断句结果不进引用链、不写回语料；引用仍然以原样原文为准，前端必须标明。
- 缓存按原文内容哈希（append-only JSONL），同一段只断一次；改了提示词就
  bump `CACHE_VERSION`，旧结果自然失效。
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import threading
from pathlib import Path
from typing import Any

import rag

# prompt 或校验口径变了就 +1，旧缓存自动失效。
CACHE_VERSION = "v2"
# 单段最多送这么多字。无标点组单 chunk 远小于此；超过就不处理，不截断——
# 截断后补出的句读会对不齐原文，比不断句更糟。
MAX_CHARS = 1500

_DEFAULT_CACHE = Path(__file__).resolve().parent.parent / "data" / "segment_cache.jsonl"

SEGMENT_PROMPT = """你在给没有标点的古籍原文补句读，只做断句，不做校勘。

规则：
1. 只允许插入标点符号，绝对不许改动、增删任何一个字，包括异体字、数字、
   空格和书名号里的字。原文的换行和空格可以保留或去掉，但字不能动。
   **不要转换繁简体或异体字**：原文用「徳」就不能写成「德」，用「髙」就不能写成「高」。
2. 可以插入的标点：，。、；：！？「」『』（）《》——……·
3. 按文言行文习惯断句：句末用「。」，句内停顿用「，」，并列用「、」，
   书名用《》，引语用「」。拿不准的地方宁可少断，不要硬断。
4. 原文中的占位符、缺字标记（如□、○）原样保留。
5. 不要翻译、不要解释、不要加注释，输出就是补好标点的同一段原文。

只输出 JSON，不要输出 JSON 以外的任何文字。JSON 格式：
{"text": "补好标点的原文"}
"""


class SegmentMismatch(ValueError):
    """模型补句读时改动了原文的字，结果不可信。"""


_CACHE: dict[str, str] = {}
_LOADED_PATH: Path | None = None
_LOCK = threading.Lock()

# 与 interpret_check 保持同一套标点口径：判定「字有没有变」时两边都去掉。
_PUNCT = re.compile(
    r"[\s，。、；：！？「」『』（）《》〈〉【】·,.;:!?()\[\]{}—…\"'“”‘’]")
_PUNCT_MARKS = re.compile(r"[，。、；：！？「」『』（）《》〈〉【】·,.;:!?()\[\]{}—…]")


def _env_flag(name: str, default: str = "1") -> bool:
    return (os.environ.get(name) or default).strip().lower() not in ("0", "false", "off", "no")


def cache_path() -> Path:
    raw = (os.environ.get("MINGLI_SEGMENT_CACHE") or "").strip()
    return Path(raw) if raw else _DEFAULT_CACHE


def _key(text: str) -> str:
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
                        continue  # 半行（进程被杀）直接跳过
                    key = row.get("key")
                    text = row.get("text")
                    if isinstance(key, str) and isinstance(text, str) and text:
                        cache[key] = text
        except FileNotFoundError:
            pass
        _CACHE = cache
        _LOADED_PATH = path


def _store(path: Path, key: str, chunk_id: int, text: str) -> None:
    row = {"key": key, "chunk_id": chunk_id, "version": CACHE_VERSION, "text": text}
    # 只存断句结果和溯源字段；key、请求头、访客 id 都不落盘。
    with _LOCK:
        _CACHE[key] = text
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError:
            pass


def same_content(source: str, candidate: str) -> bool:
    """去掉标点和空白后逐字相同——断句唯一允许的变化就是这个。"""
    return _PUNCT.sub("", source) == _PUNCT.sub("", candidate)


def _punctuation_dropped(source: str, candidate: str) -> bool:
    """原文已有的标点不能被删掉；无标点组本来就没有，这条只防偶发回退。"""
    return len(_PUNCT_MARKS.findall(candidate)) < len(_PUNCT_MARKS.findall(source))


def prepare(chunks: list[dict[str, Any]],
            force: bool = False) -> tuple[list[dict], list[tuple[dict, str, str]]]:
    """拆成「已命中缓存」和「要调模型」两部分，接口用 items 直接回前端。"""
    path = cache_path()
    _ensure_loaded(path)
    items: list[dict[str, Any]] = []
    misses: list[tuple[dict[str, Any], str, str]] = []
    for chunk in chunks:
        text = str(chunk.get("text") or "").strip()
        item = {
            "chunk_id": int(chunk["chunk_id"]),
            "text": None,
            "cached": False,
            "error": None,
        }
        items.append(item)
        if not text:
            item["error"] = "原文为空"
            continue
        if len(text) > MAX_CHARS:
            item["error"] = "这段原文过长，暂不支持自动断句，请直接读原文"
            continue
        key = _key(text)
        hit = None if force else _CACHE.get(key)
        # 旧版本缓存也可能是在更宽松的校验下写进去的；命中前再验一次，便宜且稳。
        if hit and not _valid(text, hit):
            hit = None
        if hit:
            item["text"] = hit
            item["cached"] = True
            continue
        misses.append((item, text, key))
    return items, misses


def fill(items: list[dict[str, Any]], misses: list[tuple[dict, str, str]],
         api_key: str | None = None) -> None:
    """逐条补句读。单条失败只记在那一项上，不拖垮整批。"""
    path = cache_path()
    for item, text, key in misses:
        try:
            punctuated = punctuate(text, api_key=api_key)
        except SegmentMismatch:
            item["error"] = "自动断句改动了原文的字，已放弃，请直接读原文"
            continue
        except Exception as exc:  # noqa: BLE001 - 一条失败不该让整组原文都不可读
            item["error"] = "自动断句失败：{}".format(str(exc)[:160])
            continue
        if not punctuated:
            item["error"] = "这段原文暂时无法断句"
            continue
        item["text"] = punctuated
        _store(path, key, item["chunk_id"], punctuated)


def _needs_segmentation(text: str) -> bool:
    """和前端同一口径：少于 1% 的句读标点，视为无标点组。"""
    if len(text) < 40:
        return False
    return len(_PUNCT_MARKS.findall(text)) / len(text) < 0.01


def _reject_reason(source: str, candidate: str) -> str:
    """返回不能采用的原因；能采用返回空串。原因会带进重试提示，所以写具体。"""
    if not same_content(source, candidate):
        diff = _first_diff(source, candidate)
        return "改动了原文的字" + ("（{}）".format(diff) if diff else "")
    if _punctuation_dropped(source, candidate):
        return "删掉了原文已有的标点"
    # 模型原样返回也能通过「字没变」，但那等于什么也没做。无标点段落必须真的断出句读，
    # 实测《钦定协纪辨方书》出现过整段照抄（219 字一字未加）。
    if _needs_segmentation(source) and (
            len(_PUNCT_MARKS.findall(candidate)) <= len(_PUNCT_MARKS.findall(source))):
        return "一个句读标点也没加，把原文原样返回了"
    # 长度异常：加标点最多让文本长一倍，再多基本是模型夹带了别的话。
    if len(candidate) > max(len(source) * 2 + 40, 120):
        return "输出比原文长太多，可能夹带了别的话"
    return ""


def _valid(source: str, candidate: str) -> bool:
    return not _reject_reason(source, candidate)


def _parse(raw: str) -> str:
    data = rag._parse_json(raw)
    text = data.get("text")
    if not isinstance(text, str):
        raise ValueError("模型没有返回 text 字段")
    return text.strip()


def _ask(text: str, api_key: str | None) -> str:
    messages = [
        {"role": "system", "content": SEGMENT_PROMPT},
        {"role": "user", "content": "【原文】\n{}".format(text)},
    ]
    return rag._chat(messages, api_key=api_key)


def _first_diff(source: str, candidate: str) -> str:
    """指出第一处改字，给重试提示用；没有差异返回空串。"""
    a = _PUNCT.sub("", source)
    b = _PUNCT.sub("", candidate)
    if a == b:
        return ""
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        left = a[max(0, i1 - 4):i2 + 4]
        right = b[max(0, j1 - 4):j2 + 4]
        return "原文是「{}」，你写成了「{}」".format(left, right)
    return ""


def _repair(text: str, candidate: str, reason: str, api_key: str | None) -> str:
    messages = [
        {"role": "system", "content": SEGMENT_PROMPT},
        {"role": "user", "content": "【原文】\n{}".format(text)},
        {"role": "assistant", "content": json.dumps({"text": candidate}, ensure_ascii=False)},
        {"role": "user", "content": (
            "你上一版的问题是：{}。请严格照原文重新加标点：只插标点，"
            "不能改动、增删原文任何一字，也不要转换繁简体或异体字。"
            "仍然只输出 JSON："
            '{{"text": "补好标点的原文"}}'
        ).format(reason or "没有通过校验")},
    ]
    return rag._chat(messages, api_key=api_key)


def punctuate(text: str, api_key: str | None = None) -> str:
    """调模型补句读，返回补好标点的原文。

    校验失败时带一句纠正要求重试一次；仍不一致就抛 `SegmentMismatch`，
    由调用方展示「无法自动断句」——绝不把改过字的文本当原文展示。
    """
    candidate = _parse(_ask(text, api_key))
    if not candidate:
        return ""
    reason = _reject_reason(text, candidate)
    if not reason:
        return candidate
    last, last_reason = candidate, reason
    if _env_flag("MINGLI_SEGMENT_RETRY"):
        try:
            retry = _parse(_repair(text, candidate, reason, api_key))
        except Exception:  # noqa: BLE001 - 重试失败就按第一次的结果处理
            retry = ""
        if retry:
            retry_reason = _reject_reason(text, retry)
            if not retry_reason:
                return retry
            last, last_reason = retry, retry_reason
    raise SegmentMismatch(last_reason)


def stats() -> dict[str, Any]:
    return {"cache_version": CACHE_VERSION, "cache_size": len(_CACHE),
            "max_chars": MAX_CHARS}
