# -*- coding: utf-8 -*-
"""结构解析与 chunk 元数据生成（仅用于 07/08 标点组）。

设计目标
--------
1. 直接从 ``data/clean_text/<类>/标点组/*.txt`` 解析卷、篇/类、章、节；
2. 每个 chunk 都带完整的层级元数据，不生成任何中间标记文件；
3. 供 ``src/chunk_punct.py`` 调用，也可单独运行查看每本书的解析统计。

公开接口
--------
- ``build_structure(path, book)``：解析一本书的结构；
- ``ordered_sections(st)``：按出现顺序整理成节；
- ``merge_tiny_sections(sections)``：把过短的相邻节合并成 chunk 组；
- ``build_book_chunks(category, path)``：返回一本书的全部 chunk 及统计；
- ``iter_book_chunks(category, path)``：逐条产出 chunk（兼容旧调用方式）。
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLEAN = ROOT / "data" / "clean_text"
CATS = ["07_星命七政四余", "08_八字禄命"]

GANZHI = set("甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉戌亥")
PSEUDO_GANZHI = GANZHI | {"已"}
WUXING = set("金木水火土")
CHART_EXTRA = set(
    "年月日时柱男女命造日元天干地支四柱十神长生沐浴冠带临官帝旺衰病死墓绝胎养"
    "胎元命宫身宫大运小运流年太岁正偏财官印食伤劫比肩刃杀煞"
)
HEADING_PREFIX = ("论", "释", "杂", "附", "总", "序", "跋", "说", "考", "例", "评", "注")
HEADING_SUFFIX = (
    "篇", "章", "节", "格", "法", "诀", "赋", "歌", "论", "类",
    "部", "考", "例", "说", "序", "跋", "传", "书",
)
HEADING_KW = tuple(set(HEADING_PREFIX) | set(HEADING_SUFFIX) | {"目录", "提要", "卷首", "经"})
SHISHEN_TERMS = (
    "比肩", "劫财", "败财", "食神", "伤官", "偏财", "正财",
    "七杀", "七煞", "正官", "偏印", "正印",
)
MONTH_TERMS = (
    "正月", "二月", "三月", "四月", "五月", "六月",
    "七月", "八月", "九月", "十月", "十一月", "十二月",
)
NOTE_PREFIXES = (
    "（", "(", "例一", "例二", "例三", "例四", "例五", "例六",
    "例七", "例八", "例九", "例十", "式略", "藏去声",
)

WS_RE = re.compile(r"[\s　 ]+")
SENT_PUNCT_RE = re.compile(r"[。！？，；：,;:!?]")
VERSE_PUNCT_RE = re.compile(r"[。！？，；：、,;:!?]")
PUA_RE = re.compile(r"[-]")
BAD_TITLE_END = ("也", "矣", "焉", "哉", "乎", "耳", "者", "之", "而", "则", "乃")
NUM_HEAD_RE = re.compile(
    r"^[（(【\[]?[一二三四五六七八九十百千〇○零两廿卅0-9０-９]+[）)】\]]?[、．.，,\s]+"
)
VOL_PATTERNS = [
    re.compile(r"^(第[一二三四五六七八九十百千〇○零两廿卅0-9０-９]+卷)(.*)$"),
    re.compile(r"^(卷[上中下一二三四五六七八九十百千〇○零两廿卅0-9０-９]+)(.*)$"),
    re.compile(r"^(.*卷[上中下])$"),
    re.compile(r"^(张果星宗[一二三四])$"),
    re.compile(r"^(上篇|中篇|下篇)(.*)$"),
]
# 命理探源等书的卷次标题只写「四 宜忌」，缺「卷」字，补回统一为「卷四」
BARE_PART_VOL_RE = re.compile(
    r"^([一二三四五六七八九十]+)\s*(本原|起例|强弱|宜忌|化合刑冲|先贤名论|润德堂藏稿|星家十要)$"
)
BODY_START_OVERRIDES = {
    "张果星宗": r"^张果星宗一$",
}
PART_SUFFIXES = ("篇", "论", "类", "部", "卷")
# 赋、歌、经类文本的正文本身就是短句，不能把每个短句都当标题
GENERIC_HEADINGS_DISABLED = {
    "月谈赋", "徐氏珞琭子赋注", "珞琭子三命消息赋注", "玉照神应真经",
}

# chunk 参数
TARGET = 450
MAX = 700
MIN = 120
OVERLAP = 60


# ---------------------------------------------------------------------------
# 文本清洗与标题判定
# ---------------------------------------------------------------------------

def norm_text(s: str) -> str:
    """去掉空白、零宽字符、项目符号、私用区字符，便于结构判定。"""
    s = s.replace("　", " ").strip()
    s = re.sub(r"[​-‏﻿]", "", s)
    s = re.sub(r"^[#☆★●○※\s]+", "", s)
    s = s.replace("*", "").replace("☆", "").replace("★", "")
    s = PUA_RE.sub("", s)
    return WS_RE.sub("", s)


def strip_brackets(t: str) -> str:
    t = t.strip()
    for l, r in (("《", "》"), ("【", "】"), ("(", ")"), ("（", "）"), ("[", "]"), ("〔", "〕")):
        if t.startswith(l) and t.endswith(r):
            t = t[len(l):-len(r)]
    t = t.replace("》", "").replace("】", "")
    if t.startswith("《") or t.startswith("【") or t.startswith("["):
        t = t[1:]
    return t


def toc_key(s: str) -> str:
    t = strip_brackets(norm_text(s))
    t = NUM_HEAD_RE.sub("", t)
    t = re.sub(r"[．.、，,；;：:·\-—_()（）\[\]【】《》]", "", t)
    return t


def clean_title(t: str, book: str = "") -> str:
    t = strip_brackets(norm_text(t))
    if book:
        t = re.sub(r"^" + re.escape(book) + r"[】\]》]*", "", t)
    t = re.sub(r"^[（(【\[]?\d+[）)】\]]?[、．.，,\s]*", "", t)
    t = re.sub(r"^[一二三四五六七八九十百千〇○零两廿卅]+[、．.，,\s]+", "", t)
    t = re.sub(r"^(第[一二三四五六七八九十百千〇○零两廿卅0-9０-９]+[卷章节篇])", "", t)
    t = re.sub(r"（[^）]{0,10}(补|缺|注|按|原缺|后补)[^）]{0,10}）$", "", t)
    return t.strip("、，。．.：: ")


def is_chart_like(t: str) -> bool:
    raw = norm_text(t)
    if any(term in raw for term in SHISHEN_TERMS) and sum(raw.count(x) for x in SHISHEN_TERMS) >= 2:
        return True
    if sum(1 for m in MONTH_TERMS if m in raw) >= 2:
        return True
    if re.match(r"^[甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉戌亥已]{1,4}[（(].*[）)]$", raw):
        return True
    if re.match(r"^[（(].*[）)][甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉戌亥已]{1,4}$", raw):
        return True
    t2 = re.sub(r"[\s　（）()\[\]【】{}、，,;；:：.。·\-—_]", "", raw)
    if not t2:
        return True
    gz = sum(1 for c in t2 if c in PSEUDO_GANZHI)
    if gz >= 4 and gz / len(t2) >= 0.4:
        return True
    if len(t2) <= 12 and gz >= 2 and all(c in PSEUDO_GANZHI | WUXING | CHART_EXTRA for c in t2):
        return True
    if len(t2) <= 6 and gz >= 2 and not any(k in t2 for k in HEADING_KW):
        return True
    # 八卦/方位排列表
    if len(t2) >= 4 and all(c in "乾兑离震巽坎艮坤" for c in t2):
        return True
    return False


def is_candidate(s: str) -> bool:
    t = norm_text(s)
    if not t or len(t) > 30:
        return False
    if is_chart_like(t):
        return False
    if SENT_PUNCT_RE.search(t):
        return False
    return True


def is_note_like(t: str) -> bool:
    t = norm_text(t)
    if not t:
        return True
    if not re.search(r"[一-鿿0-9０-９]", t):
        return True
    if any(t.startswith(p) for p in NOTE_PREFIXES):
        return True
    if re.match(r"^[例附][一二三四五六七八九十0-9０-９]+$", t):
        return True
    if re.match(r"^[（(].*[）)]$", t):
        return True
    if t in ("藏去声", "缺图"):
        return True
    return False


def has_heading_kw(t: str) -> bool:
    return any(k in t for k in HEADING_KW)


def looks_like_heading_title(t: str) -> bool:
    if not t or len(t) > 12:
        return False
    if any(t.startswith(p) for p in HEADING_PREFIX):
        return True
    if any(t.endswith(s) for s in HEADING_SUFFIX):
        return True
    return False


def match_volume(t: str):
    for pat in VOL_PATTERNS:
        m = pat.match(t)
        if m:
            if pat.groups >= 2:
                return m.group(1).strip(), m.group(2).strip()
            return m.group(1).strip(), ""
    m = BARE_PART_VOL_RE.match(t)
    if m:
        return "卷" + m.group(1).strip(), m.group(2).strip()
    return None


def split_heading_tokens(line: str):
    line = re.sub(r"^(本篇)?目录[：:]\s*", "", line.strip())
    parts = re.split(r"[、，。；;．]", line)
    out = []
    for p in parts:
        p = norm_text(p)
        if 2 <= len(p) <= 30 and not is_chart_like(p):
            out.append(p)
    return out


# ---------------------------------------------------------------------------
# 目录与正文起点
# ---------------------------------------------------------------------------

def collect_toc_keys(lines, start: int, end: int):
    keys = set()
    for ln in lines[start:end]:
        t = norm_text(ln)
        if not t:
            continue
        toks = split_heading_tokens(t)
        if len(toks) >= 2 or t.count("、") >= 2:
            keys.update(toc_key(x) for x in toks)
        elif is_candidate(t):
            keys.add(toc_key(t))
    return keys


def find_toc(lines, book):
    marker = None
    for i, ln in enumerate(lines[:40]):
        t = norm_text(ln)
        if "目录" in t and len(t) <= 25:
            marker = i
            break
    if marker is not None:
        if book in BODY_START_OVERRIDES:
            pat = re.compile(BODY_START_OVERRIDES[book])
            for i in range(marker + 1, len(lines)):
                if pat.match(norm_text(lines[i])):
                    return marker, i
        seen = set()
        for i in range(0, marker):
            if is_candidate(lines[i]):
                seen.add(toc_key(lines[i]))
        body = None
        for i in range(marker + 1, len(lines)):
            t = norm_text(lines[i])
            if not t:
                continue
            k = toc_key(t)
            if k and len(k) >= 1 and k in seen and i - marker >= 3:
                body = i
                break
            if is_candidate(t):
                seen.add(k)
        if body is None:
            body = marker + 1
        j = body - 1
        while j > marker and not norm_text(lines[j]):
            j -= 1
        if j > marker:
            t = norm_text(lines[j])
            if is_candidate(t) and toc_key(t) not in seen and not match_volume(t):
                body = j
        return marker, body
    cand_idx = [i for i in range(min(40, len(lines))) if is_candidate(lines[i])]
    if len(cand_idx) >= 15:
        seen = set()
        for i in range(0, len(lines)):
            if not is_candidate(lines[i]):
                continue
            k = toc_key(norm_text(lines[i]))
            if i >= 5 and k in seen and len(k) >= 1:
                return 0, i
            seen.add(k)
    return None


def next_nonempty(lines, i):
    j = i + 1
    while j < len(lines):
        if norm_text(lines[j]):
            return j
        j += 1
    return None


def prev_nonempty(lines, i):
    j = i - 1
    while j >= 0:
        if norm_text(lines[j]):
            return j
        j -= 1
    return None


def is_verse_context(lines, i):
    p = prev_nonempty(lines, i)
    n = next_nonempty(lines, i)
    if p is None or n is None:
        return False
    pt, nt = norm_text(lines[p]), norm_text(lines[n])
    return (
        len(pt) <= 20 and len(nt) <= 20
        and bool(VERSE_PUNCT_RE.search(pt)) and bool(VERSE_PUNCT_RE.search(nt))
    )


def is_prose_line(t: str) -> bool:
    return len(t) >= 18 or (len(t) >= 6 and bool(SENT_PUNCT_RE.search(t)))


# ---------------------------------------------------------------------------
# 标题识别
# ---------------------------------------------------------------------------

def extract_bracket_title(t: str):
    m = re.match(r"^[《【\[［〔]([^》】\]］〕]{1,40})[》】\]］〕]", t)
    return m.group(1).strip() if m else None


def bracket_heading(t: str):
    """只有整行像《篇名》/【篇名】的短行才是标题，避免《书名》云：…… 的长句误判。"""
    if len(t) > 60:
        return None
    if not re.match(r"^[《【\[［〔]", t):
        return None
    if not re.search(r"[》】\]］〕]", t):
        return None
    if SENT_PUNCT_RE.search(t):
        return None
    return extract_bracket_title(t)


def valid_title(t: str) -> bool:
    if not t:
        return False
    if not re.search(r"[一-鿿0-9０-９]", t):
        return False
    for l, r in (("（", "）"), ("(", ")"), ("【", "】"), ("《", "》"), ("[", "]"), ("［", "］")):
        if t.count(r) > t.count(l):
            return False
    if t.endswith(BAD_TITLE_END):
        return False
    return True


def detect_heading(lines, i, toc_keys, book, allow_generic=True):
    t = norm_text(lines[i])
    if not t or is_note_like(t) or is_signature_line(t):
        return None
    vm = match_volume(t)
    if vm:
        return ("volume", vm[0], vm[1])
    if len(t) <= 35 and re.match(
        r"^[（(【\[]?[一二三四五六七八九十百千〇○零两廿卅0-9０-９]+[）)】\]]?[、．.，,\s]", t
    ):
        title = clean_title(t, book)
        if valid_title(title):
            return ("chapter", title, "")
    m = re.match(r"^([0-9０-９]+)$", t)
    if m:
        return ("chapter", "第%s节" % m.group(1), "")
    bh = bracket_heading(t)
    if bh:
        title = clean_title(bh, book)
        if valid_title(title):
            return ("chapter", title, "")
    k = toc_key(t)
    if k in toc_keys:
        toks = split_heading_tokens(t)
        title = clean_title(toks[0] if len(toks) > 1 and toc_key(toks[0]) in toc_keys else t, book)
        if valid_title(title):
            return ("chapter", title, "")
    if len(k) >= 3 and any(tk.endswith(k) for tk in toc_keys):
        title = clean_title(t, book)
        if valid_title(title):
            return ("chapter", title, "")
    # 非卷次的“书名+序号”标题（如张果星宗六），保留完整标题便于定位
    if re.match(r"^" + re.escape(book) + r"[一二三四五六七八九十百]+$", t):
        return ("chapter", t, "")
    if not allow_generic or not is_candidate(t):
        return None
    if "、" in t:
        return None
    n = next_nonempty(lines, i)
    if n is None:
        return None
    nt = norm_text(lines[n])
    next_content = is_prose_line(nt)
    max_len = {"兰台妙选": 6, "五行精纪": 8}.get(book, 10)
    # 紧挨目录标题的上级标题
    if not next_content and toc_key(nt) in toc_keys:
        title = clean_title(t, book)
        if valid_title(title):
            return ("chapter", title, "")
    # 孤立的短标题行
    if len(t) <= max_len and next_content:
        if not is_verse_context(lines, i):
            title = clean_title(t, book)
            if valid_title(title):
                return ("chapter", title, "")
    # 含标题关键词：必须像篇名，不能是赋/歌正文或案例行
    if looks_like_heading_title(t) and len(t) <= 10 and not is_verse_context(lines, i):
        title = clean_title(t, book)
        if not valid_title(title):
            return None
        j = n
        steps = 0
        while j is not None and steps < 5:
            jt = norm_text(lines[j])
            if is_prose_line(jt):
                return ("chapter", title, "")
            j = next_nonempty(lines, j)
            steps += 1
    return None


SIGNATURE_DATE_RE = re.compile(
    r"^(公元[一二三四五六七八九十百千0-9０-９]+年|"
    r"[甲乙丙丁戊己庚辛壬癸][子丑寅卯辰巳午未申酉戌亥](孟|仲|季)?(春|夏|秋|冬)|"
    r"(乾隆|嘉庆|道光|咸丰|同治|光绪|宣统|民国)[一二三四五六七八九十百千0-9０-９]+年)"
)


def is_signature_line(t: str) -> bool:
    """题署/落款行（日期、干支纪年+季节、年号），不能当章节标题。"""
    return bool(SIGNATURE_DATE_RE.match(norm_text(t)))


def is_front_title(t, book) -> bool:
    t2 = strip_brackets(norm_text(t))
    if not t2:
        return True
    if t2 == book:
        return True
    if t2.startswith(book) and len(t2) <= len(book) + 15 and not SENT_PUNCT_RE.search(t2):
        return True
    # 形如 “七政四余乾元秘旨--舒继英” 的题名/作者行
    if book in t2 and len(t2) <= len(book) + 20 and not SENT_PUNCT_RE.search(t2):
        return True
    return False


def is_biblio_line(t, book="") -> bool:
    t2 = norm_text(t)
    if "术数类" in t2 or "命书相书之属" in t2:
        return True
    return bool(re.match(
        r"^(钦定四库全书|提要|臣等谨案|乾隆|术数类|命书相书之属|总篡官|总校官|"
        r"[^，。]{0,20}卷[上下]?（[^）]{0,15}注）|[^，。]{0,20}二卷（[^）]{0,15}注）)",
        t2,
    ))


# ---------------------------------------------------------------------------
# 结构解析
# ---------------------------------------------------------------------------

def build_structure(path: Path, book: str):
    """解析一本书：返回原始行、目录范围、目录键与带层级的内容行。"""
    lines = [ln.rstrip("\r\n") for ln in path.read_text(encoding="utf-8", errors="ignore").splitlines()]
    toc = find_toc(lines, book)
    toc_start = body_start = None
    toc_keys = set()
    if toc:
        toc_start, body_start = toc
        toc_keys = collect_toc_keys(lines, toc_start, body_start)

    allow_generic = book not in GENERIC_HEADINGS_DISABLED
    items = []
    volume = group = chapter = ""
    section_ord = 0
    seen_nonempty = 0
    first_heading_seen = False
    for i, ln in enumerate(lines):
        t = norm_text(ln)
        if not t:
            continue
        in_toc = toc_start is not None and toc_start <= i < body_start
        if in_toc:
            # 目录范围内偶尔夹着长序文（如滴天髓），保留
            if len(t) >= 40 and t.count("、") < 2 and not is_candidate(t):
                pass
            else:
                continue
        seen_nonempty += 1
        if not first_heading_seen and is_biblio_line(t, book):
            continue
        if not first_heading_seen and seen_nonempty <= 3 and is_front_title(t, book):
            continue
        # 卷内目录行（如“本篇目录：……”）不是正文
        if re.match(r"^(本篇)?目录[：:]", t):
            continue
        h = detect_heading(lines, i, toc_keys, book, allow_generic)
        if h:
            first_heading_seen = True
            section_ord += 1
            kind, title, rest = h
            if kind == "volume":
                volume = title
                group = ""
                # 卷后附带的小标题：像篇名时作 chapter，短篇名作 group
                rest_clean = clean_title(rest, book) if rest else ""
                chapter = ""
                if rest_clean:
                    if rest in toc_keys or toc_key(rest) in toc_keys or looks_like_heading_title(rest_clean):
                        chapter = rest_clean
                    elif len(rest_clean) <= 8:
                        group = rest_clean
            elif title.endswith(PART_SUFFIXES) and not chapter:
                group = title
                chapter = ""
            else:
                chapter = title
            # 标题行本身也进入正文，避免丢掉【标题】（小注）这类信息
            items.append((i + 1, t, section_ord, volume, group, chapter, True))
            continue
        # 目录后紧跟的作者/题名行
        if toc_start is not None and body_start is not None and body_start - 3 <= i <= body_start + 2:
            if len(t) <= 12 and not SENT_PUNCT_RE.search(t) and not has_heading_kw(t):
                continue
        if not re.search(r"[一-鿿0-9０-９]", t):
            continue
        items.append((i + 1, t, section_ord, volume, group, chapter, False))
    return {
        "lines": lines,
        "toc_start": toc_start,
        "body_start": body_start,
        "toc_keys": toc_keys,
        "items": items,
    }


# ---------------------------------------------------------------------------
# 分句与切块
# ---------------------------------------------------------------------------

def split_sentences(text: str):
    parts = re.split(r"([。！？；])", text)
    out = []
    buf = ""
    for p in parts:
        if not p:
            continue
        if p in "。！？；":
            buf += p
            if buf.strip():
                out.append(buf.strip())
            buf = ""
        else:
            buf += p
    if buf.strip():
        out.append(buf.strip())
    return out


def hard_split(s, limit):
    if len(s) <= limit:
        return [s]
    out = []
    while len(s) > limit:
        cut = max(s.rfind("，", 0, limit), s.rfind("、", 0, limit), s.rfind("；", 0, limit))
        if cut < limit // 2:
            cut = limit
        out.append(s[:cut + 1].strip())
        s = s[cut + 1:].strip()
    if s:
        out.append(s)
    return out


def chunk_section(lines, heading_linenos=None):
    """lines: [(text, lineno), ...] -> [{'text','line_start','line_end','char_count'}].

    heading_linenos 中的行是节标题。若当前块已经有足够正文，标题必须另起
    一块，避免出现“标题落在上一块末尾、正文在下一块”的错位。
    """
    heading_linenos = heading_linenos or set()
    sents = []
    for ln, lineno in lines:
        for s in split_sentences(ln):
            for x in hard_split(s, MAX - OVERLAP):
                sents.append((x, lineno))

    chunks = []
    cur = []
    cur_len = 0
    new_count = 0  # 当前块中来自本节的句子数（不含 overlap）
    for pos, (s, lineno) in enumerate(sents):
        # 标题尽量和它的第一句正文同块：当前块放不下“标题+下一句”时才换块
        if lineno in heading_linenos and cur:
            if not new_count:  # 只有 overlap，丢弃后让标题真正开头
                cur = []
                cur_len = 0
            else:
                next_len = len(sents[pos + 1][0]) if pos + 1 < len(sents) else 0
                if cur_len + len(s) + next_len > TARGET:
                    chunks.append(cur)
                    cur = []
                    cur_len = 0
                    new_count = 0
        if cur and cur_len + len(s) > TARGET:
            chunks.append(cur)
            # 重叠只取完整句子，且总长不超过 OVERLAP，避免 chunk 超长
            ov = []
            ov_len = 0
            for old in reversed(cur):
                if ov_len + len(old[0]) > OVERLAP:
                    break
                ov.insert(0, old)
                ov_len += len(old[0])
            cur = ov
            cur_len = ov_len
            new_count = 0
        cur.append((s, lineno))
        cur_len += len(s)
        new_count += 1
    if cur:
        chunks.append(cur)

    # 开头的标题/短句不足以单独成块时并入下一块
    if len(chunks) >= 2 and sum(len(x[0]) for x in chunks[0]) < MIN:
        if sum(len(x[0]) for x in chunks[0]) + sum(len(x[0]) for x in chunks[1]) <= MAX + OVERLAP:
            chunks[1] = chunks[0] + chunks[1]
            chunks.pop(0)
    # 结尾的短块尽量并入上一块
    if len(chunks) >= 2 and sum(len(x[0]) for x in chunks[-1]) < MIN:
        if sum(len(x[0]) for x in chunks[-2]) + sum(len(x[0]) for x in chunks[-1]) <= MAX:
            chunks[-2].extend(chunks[-1])
            chunks.pop()

    out = []
    for c in chunks:
        text = "\n".join(x[0] for x in c).strip()
        if not text:
            continue
        out.append({
            "text": text,
            "line_start": min(x[1] for x in c),
            "line_end": max(x[1] for x in c),
            "char_count": len(text),
        })
    return out


# ---------------------------------------------------------------------------
# 节合并与元数据
# ---------------------------------------------------------------------------

def ordered_sections(st):
    order = []
    secs = {}
    for lineno, text, so, vol, grp, ch, is_heading in st["items"]:
        if so not in secs:
            secs[so] = {
                "section_ord": so,
                "volume": vol,
                "group": grp,
                "chapter": ch,
                "heading_lineno": None,
                "lines": [],
                "linenos": [],
            }
            order.append(so)
        if is_heading and secs[so]["heading_lineno"] is None:
            secs[so]["heading_lineno"] = lineno
        secs[so]["lines"].append(text)
        secs[so]["linenos"].append(lineno)
    return [secs[k] for k in order]


def section_chars(sec):
    return sum(len(x) for x in sec["lines"])


def merge_tiny_sections(secs):
    """把同一卷内连续的短节合并，避免一个标题行就成一个 chunk。"""
    groups = []
    i = 0
    while i < len(secs):
        cur = secs[i]
        cur_chars = section_chars(cur)
        if cur_chars >= MIN:
            groups.append([cur])
            i += 1
            continue
        grp = [cur]
        total = cur_chars
        j = i + 1
        while j < len(secs) and total < TARGET and len(grp) < 12:
            nxt = secs[j]
            if nxt["volume"] != cur["volume"]:
                break
            nxt_chars = section_chars(nxt)
            grp.append(nxt)
            total += nxt_chars
            j += 1
            if nxt_chars >= TARGET:
                break
        groups.append(grp)
        i = j
    return groups


def group_meta(grp, book, category, rel):
    first, last = grp[0], grp[-1]
    # 优先用章名；没有章名时才退回篇/类名，避免把 group 和 chapter 混成一个标签
    titles = []
    for s in grp:
        t = s["chapter"]
        if t and t != s["volume"] and t not in titles:
            titles.append(t)
    if not titles:
        for s in grp:
            t = s["group"]
            if t and t != s["volume"] and t not in titles:
                titles.append(t)
    if not titles:
        titles = [first["volume"] or "正文"]
    if len(titles) == 1:
        chapter = titles[0]
    else:
        chapter = " / ".join(titles[:4]) + (" 等" if len(titles) > 4 else "")

    volume = first["volume"]
    group = first["group"] if all(s["group"] == first["group"] for s in grp) else ""
    section_path = []
    for x in (volume, group, chapter):
        if x and x not in section_path:
            section_path.append(x)

    section_id = "S%04d" % first["section_ord"]
    if last["section_ord"] != first["section_ord"]:
        section_id += "-S%04d" % last["section_ord"]
    return {
        "book": book,
        "category": category,
        "volume": volume,
        "group": group,
        "chapter": chapter,
        "section_titles": titles,
        "section_path": section_path,
        "section_id": section_id,
        "line_start": min(first["linenos"]),
        "line_end": max(last["linenos"]),
        "sourcefile": rel,
    }


def classify_texts(texts):
    lines = [norm_text(x) for x in texts if norm_text(x)]
    if not lines:
        return "body"
    avg_len = sum(len(x) for x in lines) / len(lines)
    max_len = max(len(x) for x in lines)
    chart = sum(1 for x in lines if is_chart_like(x))
    # 只有整体短、没有大段注文的组才判为命盘/表格
    if chart / len(lines) >= 0.6 and avg_len <= 60 and max_len <= 150:
        return "chart"
    short = [x for x in lines if len(x) <= 20]
    if len(short) / len(lines) >= 0.6 and max_len <= 40:
        return "verse"
    return "body"


def chunk_stats(chunks):
    lens = sorted(c["char_count"] for c in chunks)
    if not lens:
        return {"n": 0, "p50": 0, "p90": 0, "min": 0, "max": 0, "small": 0, "chars_total": 0}
    return {
        "n": len(lens),
        "p50": lens[len(lens) // 2],
        "p90": lens[max(0, int(len(lens) * 0.9) - 1)],
        "min": lens[0],
        "max": lens[-1],
        "small": sum(1 for x in lens if x < MIN),
        "chars_total": sum(lens),
    }


# ---------------------------------------------------------------------------
# 对外生成接口
# ---------------------------------------------------------------------------

def strip_heading_prefix(text: str, base: dict) -> str:
    """去掉正文开头与层级标签完全相同的标题行，避免 embedding 文本重复。"""
    labels = set(base.get("section_titles") or [])
    for key in ("volume", "group", "chapter"):
        value = base.get(key)
        if value:
            labels.add(value)
    label_keys = {toc_key(x) for x in labels if x}
    lines = text.splitlines()
    while lines and toc_key(lines[0]) in label_keys:
        lines.pop(0)
    return "\n".join(lines).strip() or text


def build_book_chunks(category: str, path: Path, clean_root: Path | None = None):
    """返回一本书的全部 chunk、结构统计与元数据覆盖率。"""
    clean_root = Path(clean_root) if clean_root is not None else CLEAN
    book = path.stem
    try:
        rel = path.resolve().relative_to(clean_root.resolve()).as_posix()
    except ValueError:
        rel = path.name

    st = build_structure(path, book)
    secs = ordered_sections(st)
    groups = merge_tiny_sections(secs)

    rows = []
    for grp in groups:
        base = group_meta(grp, book, category, rel)
        lines = []
        for sec in grp:
            lines.extend(zip(sec["lines"], sec["linenos"]))
        heading_linenos = {
            sec["heading_lineno"] for sec in grp if sec.get("heading_lineno") is not None
        }
        chunks = chunk_section(lines, heading_linenos)
        if not chunks:
            continue
        ctype = classify_texts([text for sec in grp for text in sec["lines"]])
        path_bits = " · ".join(base["section_path"])
        for idx, c in enumerate(chunks, 1):
            meta = dict(base)
            meta.update({
                "chunk_index": idx,
                "chunk_total": len(chunks),
                "line_start": c["line_start"],
                "line_end": c["line_end"],
                "char_count": c["char_count"],
                "chunk_type": ctype,
                "has_punctuation": bool(SENT_PUNCT_RE.search(c["text"])),
            })
            meta["chunk_uid"] = "%s/%s/%s/C%04d" % (category, book, base["section_id"], idx)
            embed_text = strip_heading_prefix(c["text"], base)
            meta["text_for_embedding"] = "《%s》%s\n%s" % (
                book,
                (" · " + path_bits) if path_bits else "",
                embed_text,
            )
            rows.append({
                "sourcefile": rel,
                "chunk_id": None,
                "chunk_text": c["text"],
                "meta": meta,
            })

    stats = chunk_stats([r["meta"] for r in rows])
    stats.update({
        "book": book,
        "category": category,
        "sourcefile": rel,
        "lines": len(st["lines"]),
        "toc_start": st["toc_start"],
        "body_start": st["body_start"],
        "toc_keys": len(st["toc_keys"]),
        "sections": len(secs),
        "groups": len(groups),
        "chunk_types": dict(Counter(r["meta"]["chunk_type"] for r in rows)),
        "missing_volume": sum(1 for r in rows if not r["meta"].get("volume")),
        "missing_chapter": sum(1 for r in rows if not r["meta"].get("chapter")),
        "missing_section_path": sum(1 for r in rows if not r["meta"].get("section_path")),
    })
    return {
        "book": book,
        "category": category,
        "sourcefile": rel,
        "sections": len(secs),
        "groups": len(groups),
        "chunks": rows,
        "stats": stats,
    }


def iter_book_chunks(category: str, path: Path, clean_root: Path | None = None):
    """逐条产出 chunk，便于流式写出。"""
    result = build_book_chunks(category, path, clean_root)
    for row in result["chunks"]:
        yield row


def main():
    """dry-run：只打印解析统计，不写任何文件。"""
    total_books = 0
    total_chunks = 0
    for cat in CATS:
        dp = CLEAN / cat / "标点组"
        if not dp.exists():
            print(f"[跳过] 目录不存在：{dp}")
            continue
        for path in sorted(dp.glob("*.txt")):
            result = build_book_chunks(cat, path)
            s = result["stats"]
            total_books += 1
            total_chunks += s["n"]
            print(
                f"{result['book']} [{cat}] lines={s['lines']} sections={s['sections']} "
                f"groups={s['groups']} chunks={s['n']} p50={s['p50']} p90={s['p90']} "
                f"max={s['max']} small={s['small']} types={s['chunk_types']}"
            )
    print(f"合计：{total_books} 本，{total_chunks} 个 chunk")


if __name__ == "__main__":
    main()
