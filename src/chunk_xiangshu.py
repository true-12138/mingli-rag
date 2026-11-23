# -*- coding: utf-8 -*-
"""11_相术 的补录 chunk 入口（面相 / 手相语料）。

为什么单独一个文件
------------------
07/08 的标点组走 ``chunk_punct.py``（有卷篇结构），11_相术 的文本既没有
统一的卷次标题，也不全是无标点文本，塞进哪一边都会把那一组的统计弄脏。
之前只有三本（太清神鉴、玉管照神局、人伦大统赋）因为标点率 < 2% 被
``chunk_unpunct.py`` 顺手收进去了，剩下十本一直没入库——手相检索弱，
根子在这里。这个脚本只补这十本，不动已有产物，也不改前两组编号。
2026-11-22 又从 wt38.com 补了《神相全編》卷八（掌纹专卷），
用 ``APPEND_LAST`` 固定建在末尾，已有 chunk_id 与 eval 金标不动。
卷八先按普通长块切成 26 块，手相 7 题只中 3 道；当晚改成按纹名 /
【小标题】细切（目标约 190 字、上限 260 字），26 → 107 块，7 题全中。
``text_for_embedding`` 折叠繁简并前置纹名，避免「鴈陣紋」查不到。

做法
----
1. 逐行读，先去掉四库本的版心/提要样板行（「钦定四库全书」「【臣】等谨案」等）；
2. 单行超过 MAX 的，按句末标点（。！？；）切成若干段，不丢字；
3. 短段并入相邻段，再按 TARGET 组 chunk，overlap 只取完整段落；
4. 卷/篇/章留空：相术书抄本差异大，硬解析标题只会造出假结构。

输出::

    data/chunks/xiangshu.jsonl         每行 = 一个 chunk + 内嵌 meta
    data/chunks/xiangshu_report.json   每本书的统计
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

try:  # 作为包导入
    from .chunk_meta import TARGET, MAX, MIN, OVERLAP, chunk_stats
    from .retrieval_utils import ENTRY_NAME_RE, fold_simplified
except ImportError:  # 直接运行 src/chunk_xiangshu.py
    from chunk_meta import TARGET, MAX, MIN, OVERLAP, chunk_stats
    from retrieval_utils import ENTRY_NAME_RE, fold_simplified

ROOT = Path(__file__).resolve().parents[1]
CLEAN = ROOT / "data" / "clean_text"
CATEGORY = "11_相术"
GROUP_NAME = "相术组"

OUT_CHUNKS = ROOT / "data" / "chunks" / "xiangshu.jsonl"
OUT_REPORT = ROOT / "data" / "chunks" / "xiangshu_report.json"

# 这三本的标点率低于 2%，已经在 unpunct.jsonl 里，重复收录会让同一段文字
# 出现两次、挤占召回名额。要迁移走它们，必须同时重跑 embed 和改编号。
ALREADY_INDEXED = {"太清神鉴", "玉管照神局", "人伦大统赋"}

# chunk_id 是按书连号的（见 src/corpus.py），eval 的金标 id 又是写死的数字。
# 2026-11-22 补的《神相全編·卷八》按文件名会排在中间，插进去会把后面每本书的
# 编号都顶掉；固定建在末尾，新 id 从 9613 起，旧金标不动。
APPEND_LAST = {"神相全編·卷八"}

# 卷八是《神相全编》的一卷，不是第 56 部书：book 归到正编，列表/引用才不会
# 把同一部书算两次。chunk_uid 和 text_for_embedding 仍用文件名，一是避免与正编
# 的 C0001.. 撞号，二是保持已编码的 26 条向量不变（前缀不同则必须重编码）。
BOOK_ALIAS = {"神相全編·卷八": "神相全编"}

SENT_END = "。！？；!?;"
BOILERPLATE = (
    re.compile(r"^钦定[四四庫库]全书"),
    re.compile(r"^【臣】等[谨謹]案"),
    re.compile(r"^臣等[谨謹]案"),
    re.compile(r"^提要$"),
    re.compile(r"^[术術][数數]类"),
    re.compile(r"^子部[七]"),
    re.compile(r"^[\s　]*$"),
)


def _utf8_stdout():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def read_lines(path: Path):
    """返回 [(行文本, 行号)]，去掉空行、首尾行款和四库样板行。行号保留原文行号。"""
    out = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        text = raw.strip(" \t　 ")
        if not text:
            continue
        if any(p.search(text) for p in BOILERPLATE):
            continue
        out.append((text, lineno))
    return out


def split_sentences(text: str):
    """按句末标点切段，标点留在前一段末尾。只用于超长行。"""
    pieces, buf = [], ""
    for ch in text:
        buf += ch
        if ch in SENT_END:
            pieces.append(buf)
            buf = ""
    if buf:
        pieces.append(buf)
    return [p for p in pieces if p.strip()]


def to_paragraphs(lines):
    """把行拆成不超过 MAX 的段。长行按句切；单句仍超长时硬切。"""
    paras = []
    for text, lineno in lines:
        if len(text) <= MAX:
            paras.append({"text": text, "line_start": lineno, "line_end": lineno, "n_lines": 1})
            continue
        buf = ""
        for sent in split_sentences(text):
            while len(sent) > MAX:
                paras.append({"text": sent[:MAX], "line_start": lineno,
                              "line_end": lineno, "n_lines": 1})
                sent = sent[MAX:]
            if buf and len(buf) + len(sent) > MAX:
                paras.append({"text": buf, "line_start": lineno,
                              "line_end": lineno, "n_lines": 1})
                buf = ""
            buf += sent
        if buf:
            paras.append({"text": buf, "line_start": lineno,
                          "line_end": lineno, "n_lines": 1})
    return paras


def merge_tiny(paras):
    """短段向后并入相邻段，避免标题行单独成块。"""
    out, buf = [], None

    def concat(a, b):
        return {
            "text": a["text"] + b["text"],
            "line_start": min(a["line_start"], b["line_start"]),
            "line_end": max(a["line_end"], b["line_end"]),
            "n_lines": a["n_lines"] + b["n_lines"],
        }

    for p in paras:
        buf = dict(p) if buf is None else concat(buf, p)
        if len(buf["text"]) >= MIN:
            out.append(buf)
            buf = None
    if buf is not None:
        if out:
            out[-1] = concat(out[-1], buf)
        else:
            out.append(buf)
    return out


def group_chunks(paras):
    """按 TARGET 组成 chunk；overlap 只取完整段落。"""
    chunks, cur, cur_len = [], [], 0

    for p in paras:
        if cur and cur_len + len(p["text"]) > TARGET:
            chunks.append(cur)
            ov, ov_len = [], 0
            for old in reversed(cur):
                if ov_len + len(old["text"]) > OVERLAP:
                    break
                ov.insert(0, old)
                ov_len += len(old["text"])
            cur, cur_len = ov, ov_len
        cur.append(p)
        cur_len += len(p["text"])
    if cur:
        chunks.append(cur)

    if len(chunks) >= 2 and sum(len(x["text"]) for x in chunks[0]) < MIN:
        chunks[1] = chunks[0] + chunks[1]
        chunks.pop(0)
    if len(chunks) >= 2 and sum(len(x["text"]) for x in chunks[-1]) < MIN:
        chunks[-2].extend(chunks[-1])
        chunks.pop()

    out = []
    for c in chunks:
        text = " ".join(x["text"] for x in c)
        if not text.strip():
            continue
        out.append({
            "text": text,
            "line_start": min(x["line_start"] for x in c),
            "line_end": max(x["line_end"] for x in c),
            "char_count": len(text),
            "paragraphs": len(c),
        })
    return out


# 卷八是一次性补录的掌纹专卷：原文把十几条纹排在一个 400+ 字的大段落里，
# 「玉柱紋」这类专名在块内的权重被稀释到 1/15，检索排不进前五。
# 补录卷不参与历史编号，可以按条目重切：以纹名或【小标题】为界，
# 每块约 190 字、最多 260 字，一个条目或几个相邻条目一块。
APP_SPLIT_TARGET = 190
APP_SPLIT_MAX = 260


def split_appendix_text(text: str):
    """按句末标点切句，再按「纹名开头/【小标题】」的条目边界聚成小块。"""
    sents = [s for s in re.split(r"(?<=[。！？；])", text) if s.strip()]
    out, buf = [], ""
    for s in sents:
        st = s.strip()
        starts_entry = bool(ENTRY_NAME_RE.match(st)) or st.startswith("【")
        if buf and (len(buf) + len(s) > APP_SPLIT_TARGET
                    or (starts_entry and len(buf) >= 60)):
            out.append(buf.strip())
            buf = ""
        buf += s
        if len(buf) >= APP_SPLIT_MAX:
            out.append(buf.strip())
            buf = ""
    if buf.strip():
        out.append(buf.strip())
    return out


def resplit_appendix(chunks):
    out = []
    for c in chunks:
        for t in split_appendix_text(c["text"]):
            out.append({
                "text": t,
                "line_start": c["line_start"],
                "line_end": c["line_end"],
                "char_count": len(t),
                "paragraphs": 1,
            })
    return out


def build_book(path: Path):
    stem = path.stem
    book = BOOK_ALIAS.get(stem, stem)
    rel = _rel(path)
    raw = path.read_text(encoding="utf-8")
    punct = sum(1 for ch in raw if ch in "。！？，；：、,;:!?")
    rate = punct / len(raw) if raw else 0.0

    lines = read_lines(path)
    paras = merge_tiny(to_paragraphs(lines))
    chunks = group_chunks(paras)
    if path.stem in APPEND_LAST:
        chunks = resplit_appendix(chunks)

    rows = []
    for idx, c in enumerate(chunks, 1):
        meta = {
            "book": book,
            "category": CATEGORY,
            "volume": "",
            "group": GROUP_NAME,
            "chapter": "",
            "section_titles": [],
            "section_path": [GROUP_NAME],
            "section_id": "X",
            "sourcefile": rel,
            "chunk_index": idx,
            "chunk_total": len(chunks),
            "line_start": c["line_start"],
            "line_end": c["line_end"],
            "char_count": c["char_count"],
            "paragraphs": c["paragraphs"],
            "chunk_type": "xiangshu",
            "has_punctuation": True,
            "punct_rate": round(rate, 6),
        }
        meta["chunk_uid"] = "%s/%s/X/C%04d" % (CATEGORY, stem, idx)
        if stem in APPEND_LAST:
            # 向量用折叠繁简的文本 + 条目名清单：用户问「雁阵纹」而原文写
            # 「鴈陣紋」，不折叠的话 dense 也排到 89 名开外。
            names = [fold_simplified(n) for n in ENTRY_NAME_RE.findall(c["text"])]
            meta["text_for_embedding"] = "《%s》\n%s\n%s" % (
                stem, "、".join(names), fold_simplified(c["text"]))
        else:
            meta["text_for_embedding"] = "《%s》\n%s" % (stem, c["text"])
        rows.append({
            "sourcefile": rel,
            "chunk_id": None,
            "chunk_text": c["text"],
            "meta": meta,
        })

    stats = chunk_stats([r["meta"] for r in rows])
    stats.update({
        "book": book,
        "category": CATEGORY,
        "sourcefile": rel,
        "lines": len(lines),
        "paragraphs": len(paras),
        "punct_rate": round(rate, 6),
    })
    return {"book": book, "chunks": rows, "stats": stats}


def iter_books():
    base = CLEAN / CATEGORY
    paths = [p for p in base.glob("*.txt") if p.stem not in ALREADY_INDEXED]
    for path in sorted(paths, key=lambda p: (p.stem in APPEND_LAST, p.stem)):
        yield path


def main() -> int:
    _utf8_stdout()
    OUT_CHUNKS.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT_CHUNKS.with_name(OUT_CHUNKS.name + ".tmp")

    books, errors = [], []
    chunk_id = 0
    total_chars = 0

    with open(tmp, "w", encoding="utf-8", newline="\n") as fc:
        for path in iter_books():
            try:
                result = build_book(path)
            except Exception as exc:  # 保住其他书的产出
                errors.append(f"{_rel(path)}: {type(exc).__name__}: {exc}")
                print(f"  [失败] {path.name}: {exc}")
                continue

            rows = result["chunks"]
            for row in rows:
                chunk_id += 1
                row["chunk_id"] = chunk_id
                fc.write(json.dumps(row, ensure_ascii=False) + "\n")

            stats = dict(result["stats"])
            stats["chunk_id_start"] = chunk_id - len(rows) + 1 if rows else None
            stats["chunk_id_end"] = chunk_id if rows else None
            books.append(stats)
            total_chars += stats["chars_total"]
            print(
                f"  {result['book']}: {stats['n']} chunks | lines={stats['lines']} "
                f"paras={stats['paragraphs']} | p50={stats['p50']} p90={stats['p90']} "
                f"max={stats['max']} small={stats['small']}"
            )

    tmp.replace(OUT_CHUNKS)

    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "script": _rel(Path(__file__)),
        "scope": {
            "dir": _rel(CLEAN / CATEGORY),
            "excluded_already_indexed": sorted(ALREADY_INDEXED),
        },
        "params": {
            "target": TARGET, "max": MAX, "min": MIN, "overlap": OVERLAP,
        },
        "books": books,
        "totals": {"books": len(books), "chunks": chunk_id, "chars": total_chars},
        "errors": errors,
    }
    OUT_REPORT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print("\n" + "=" * 60)
    print(f"补录 {len(books)} 本，{chunk_id} chunks，{total_chars} 字")
    print(f"输出：{_rel(OUT_CHUNKS)}")
    if errors:
        print(f"有 {len(errors)} 个错误：")
        for err in errors:
            print("  -", err)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
