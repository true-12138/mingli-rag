# -*- coding: utf-8 -*-
"""古籍问答 · 排盘：Streamlit 界面。

给访客看的只有两件事：问古籍、排盘。检索策略、Agent 编排、评测账本都是
内部工具，默认不出现；维护时用 MINGLI_ADMIN=1 或 URL 加 ?admin=1 打开。

视觉沿用「纸、墨、朱砂」：纸是底，墨是字，朱砂只用在印章和原文出处上。
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
import time as _time
from datetime import date, datetime, time, timedelta
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

# 无论从仓库根目录还是 src/ 内部启动，都能找到同级模块
sys.path.append(str(Path(__file__).resolve().parent))

from fortune.astro import SIGNS, format_chart, natal_chart
from fortune.bazi import format_bazi, paipan
from fortune.interpret import has_api_key, read
from fortune.tarot import SPREADS, draw as draw_tarot
from fortune.tarot import format_draw

CITIES = {
    "北京": (39.90, 116.40),
    "上海": (31.23, 121.47),
    "深圳": (22.54, 114.06),
    "广州": (23.13, 113.26),
    "杭州": (30.27, 120.16),
    "成都": (30.57, 104.07),
    "武汉": (30.59, 114.31),
    "西安": (34.34, 108.94),
}

# 示例问题都能在语料里找到依据；点一下就直接发出去。
EXAMPLES = (
    "七杀和偏官是同一个神吗？",
    "伤官见官，为祸百端，是不是一定不好？",
    "官杀混杂，什么时候能一起看，什么时候必须分开？",
    "纳音五行和正五行，谁说了算？",
)

CSS = "<style>" + (Path(__file__).with_name("app_theme.css")).read_text(encoding="utf-8") + "</style>"

# 回答里的引用编号 [1] 显示成上标，和出处列表对应
_SUP = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")


def _esc(value):
    return html.escape(str(value or ""))


def _chips(items, seal=False):
    cls = "chip seal" if seal else "chip"
    return '<div class="chips">%s</div>' % "".join(
        '<span class="%s">%s</span>' % (cls, _esc(x)) for x in items
    )


def _panel(kind, title, body):
    st.markdown(
        '<div class="panel panel-%s"><div class="panel-title">%s</div>'
        '<div class="panel-body">%s</div></div>' % (kind, _esc(title), _esc(body)),
        unsafe_allow_html=True,
    )


# ---------- 额度闸门 ----------
# 公网 Demo 没有登录态，谁都能点。真正要防的不是「人」，是脚本循环刷调用：
# 单会话限制挡不住脚本（换个 session 就重置），全站每日上限才是硬闸门。
# 只有用**服务端 key** 时才计数——访客自带 key 花的是他自己的钱。

DAILY_LLM_LIMIT = int(os.environ.get("MINGLI_DAILY_LLM_LIMIT", "300"))
SESSION_LLM_LIMIT = int(os.environ.get("MINGLI_SESSION_LLM_LIMIT", "6"))


def _quota_path():
    root = Path(os.environ.get("MINGLI_DATA_DIR") or (Path(__file__).resolve().parent.parent / "data"))
    return root / ".quota.json"


def _quota_used_today():
    try:
        data = json.loads(_quota_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    return int((data or {}).get(datetime.now().strftime("%Y-%m-%d"), 0))


def _quota_take():
    """占用一次调用额度。返回 (是否放行, 提示语)。"""
    used_session = int(st.session_state.get("llm_used", 0))
    if used_session >= SESSION_LLM_LIMIT:
        return False, "本次会话的免费次数已用完（%d 次）。刷新页面可重置，或填入自己的 Key。" % SESSION_LLM_LIMIT

    day = datetime.now().strftime("%Y-%m-%d")
    used = _quota_used_today()
    if used >= DAILY_LLM_LIMIT:
        return False, "今日全站免费额度已用完（%d 次/天）。明天再来，或填入自己的 Key。" % DAILY_LLM_LIMIT

    path = _quota_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if not isinstance(data, dict):
            data = {}
        data[day] = used + 1
        # 只留最近 7 天，别让计数文件长成日志
        keep = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d")
        for k in [k for k in data if k < keep]:
            data.pop(k, None)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass  # 写不了计数文件就不拦：宁可漏一次，也别把功能挡死
    st.session_state["llm_used"] = used_session + 1
    return True, ""


TOPIC_PROMPTS = (
    ("感情", "请结合盘面，重点讲讲我的感情与相处方式。"),
    ("事业", "请结合盘面，重点讲讲我的事业方向与适合的工作方式。"),
    ("学业", "请结合盘面，重点讲讲我的学业与适合的学习方式。"),
    ("财运", "请结合盘面，重点讲讲我的财务倾向与用钱方式。"),
)


# ---------- 外壳 ----------

def _admin_enabled():
    if os.environ.get("MINGLI_ADMIN", "").strip().lower() in ("1", "true", "yes", "on"):
        return True
    try:
        return str(st.query_params.get("admin") or "").strip() == "1"
    except Exception:
        return False


def _header():
    views = ["问古籍", "排盘"] + (["维护"] if _admin_enabled() else [])
    left, right = st.columns([0.62, 0.38], gap="small", vertical_alignment="center")
    left.markdown(
        '<div class="brand-row">'
        '<span class="seal-mark">古</span>'
        '<span class="brand-name">问古</span>'
        '<span class="brand-sub">古籍问答</span>'
        '</div>',
        unsafe_allow_html=True,
    )
    view = right.radio(
        "页面", views, index=0, horizontal=True,
        label_visibility="collapsed", key="nav_view",
    )
    st.markdown('<div class="head-rule"></div>', unsafe_allow_html=True)
    return view


def _key_panel():
    """没有服务端 Key 时，让访客自带一个；只存在本次会话，不落盘。"""
    if has_api_key():
        return None
    with st.expander("使用自己的 DeepSeek Key", expanded=True):
        st.caption("公网演示没有配置服务端 Key。Key 只用于本次会话，不写日志、不落盘。")
        st.text_input(
            "DeepSeek API Key", type="password", key="qa_key",
            label_visibility="collapsed", placeholder="sk-…",
        )
    return st.session_state.get("qa_key") or None


# ---------- 古籍问答 ----------

def _as_history(messages):
    """只把真正的问答内容传给后端；错误提示和 UI 元数据不进上下文。"""
    out = []
    for m in messages:
        if m.get("role") in ("user", "assistant") and not m.get("error"):
            text = (m.get("content") or "").strip()
            if text:
                out.append({"role": m["role"], "content": text})
    # 上一轮失败时只剩一条没有回答的 user，不能当成完整轮次带进改写
    while out and out[-1]["role"] == "user":
        out.pop()
    return out


@st.cache_resource(show_spinner=False)
def _chunk_index():
    import retrieval

    return {str(c["chunk_id"]): c for c in retrieval.chunks}


def _source_items(res):
    """把模型引用的 chunk_id 还原成可展示的原文。"""
    index = _chunk_index()
    seen, items = set(), []
    for cid in res.get("citations_chunk_ids") or []:
        key = str(cid)
        if key in seen:
            continue
        seen.add(key)
        chunk = index.get(key)
        if not chunk:
            continue
        meta = chunk.get("meta") or {}
        parts = [str(meta.get(k) or "").strip() for k in ("book", "volume", "chapter")]
        title = "《{}》".format("·".join(p for p in parts if p)) if any(parts) else "《未标书名》"
        text = (chunk.get("chunk_text") or "").strip()
        items.append({
            "title": title,
            "book": str(meta.get("book") or "").strip(),
            "text": text,
        })
    return items


def _source_block(items):
    chips = "".join(
        '<span class="source-chip"><b>%d</b>&nbsp;%s</span>' % (i + 1, _esc(it["title"]))
        for i, it in enumerate(items)
    )
    st.markdown(
        '<div class="source-strip"><span class="source-label">原文出处</span>%s</div>' % chips,
        unsafe_allow_html=True,
    )
    with st.expander("查看 %d 段原文" % len(items), expanded=False):
        for it in items:
            text = it["text"]
            if len(text) > 700:
                text = text[:700] + "……"
            st.markdown(
                '<div class="source-quote"><div class="source-head">%s</div>'
                '<div class="source-text">%s</div></div>'
                % (_esc(it["title"]), _esc(text).replace("\n", "<br>")),
                unsafe_allow_html=True,
            )


def _followup_items(res):
    books = []
    for it in _source_items(res):
        if it["book"] and it["book"] not in books:
            books.append(it["book"])
    items = []
    if books:
        items.append(("《%s》里还怎么说？" % books[0],
                      "《%s》里还怎么说？" % books[0]))
    items.append(("用更直白的话讲一遍",
                  "用更直白的话把刚才的回答讲一遍，并保留原文出处。"))
    if len(books) > 1:
        items.append(("换部书对照一下",
                      "《%s》和《%s》对这个问题的说法有什么区别？" % (books[0], books[1])))
    elif not books:
        items.append(("有没有相反的说法？", "古籍里对这个说法有没有相反的意见？"))
    return items[:3]


def _refusal_panel(res):
    reason = (res.get("refusal_reason") or "").strip()
    st.markdown(
        '<div class="panel panel-refusal">'
        '<div class="panel-title">这句古籍里没有直接依据</div>'
        '<div class="panel-body">%s</div>'
        '<div class="panel-help">可以换一个更具体的问法，或者先问一个相关术语。</div>'
        '</div>' % _esc(reason or "检索到的段落只是主题相近，不能直接回答问题，所以不硬答。"),
        unsafe_allow_html=True,
    )


def _render_answer(msg, idx):
    res = msg.get("meta") or {}
    if msg.get("error"):
        _panel("notice", "这次没有回答成功",
               "可能是网络或额度问题。稍后再试一次，或者把问题拆小一点。")
        if _admin_enabled() and msg.get("detail"):
            with st.expander("技术信息"):
                st.code(msg["detail"])
        return

    if res.get("can_answer") is None:
        _panel("notice", "这次没有生成可用的回答",
               "模型输出没有通过格式校验。换一种问法，或者再试一次。")
        return

    if res.get("can_answer") is False:
        _refusal_panel(res)
        return

    content = (msg.get("content") or "").strip()
    if content:
        # [1] → [¹]：正文里的编号不抢戏，和下面的出处一一对应。
        content = re.sub(
            r"\[(\d{1,2})\]", lambda m: "[%s]" % m.group(1).translate(_SUP),
            content,
        )
        st.markdown(content)
    else:
        _panel("notice", "回答是空的", "模型没有给出正文。可以再问一次，或换一种问法。")

    items = _source_items(res)
    if items:
        _source_block(items)
    elif res.get("can_answer"):
        st.markdown(
            '<div class="caution">这条回答没有可核对的原文出处，请只当作参考。</div>',
            unsafe_allow_html=True,
        )

    items_to_ask = _followup_items(res)
    if items_to_ask:
        st.markdown('<div class="follow-label">继续问</div>', unsafe_allow_html=True)
        cols = st.columns(len(items_to_ask), gap="small")
        for i, (label, prompt) in enumerate(items_to_ask):
            if cols[i].button(label, key="follow_%d_%d" % (idx, i), use_container_width=True):
                st.session_state["qa_pending"] = prompt
                st.rerun()


def _render_user(question):
    st.markdown(
        '<div class="q-row"><div class="q-bubble">%s</div></div>' % _esc(question),
        unsafe_allow_html=True,
    )


def _empty_state():
    st.markdown(
        '<div class="hero">'
        '<h1>问古籍，得原文</h1>'
        '<p class="hero-sub">古籍里的一个词、一句断语，回到四十五部古籍里找依据。'
        '找不到，它会直说。</p>'
        '</div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="section-label">可以这样问</div>', unsafe_allow_html=True)
    rows = [EXAMPLES[i:i + 2] for i in range(0, len(EXAMPLES), 2)]
    for r, pair in enumerate(rows):
        cols = st.columns(len(pair), gap="small")
        for c, question in enumerate(pair):
            if cols[c].button(question, key="ex%d_%d" % (r, c), use_container_width=True):
                st.session_state["qa_pending"] = question
                st.rerun()
    st.markdown(
        '<p class="fineprint">点问题直接发。也可以追问「那《三命通会》里怎么说？」——'
        '回答只引用检索到的原文，引用不足时会拒答。</p>',
        unsafe_allow_html=True,
    )
    # st.chat_input 会挂在页底并把主区滚到底，首屏的页眉和问候会被顶出视口。
    # 首屏没有对话，滚回顶部；有对话后交给 Streamlit 自己滚到最新一条。
    components.html(
        """<script>
        (function () {
          var doc = window.parent.document;
          function goTop() {
            var main = doc.querySelector('section[data-testid="ScrollToBottomContainer"]');
            if (main) main.scrollTop = 0;
            window.parent.scrollTo(0, 0);
          }
          goTop();
          [80, 300, 800, 1500].forEach(function (t) { setTimeout(goTop, t); });
        })();
        </script>""",
        height=0,
    )


def _chat_title():
    left, right = st.columns([0.72, 0.28], gap="small", vertical_alignment="center")
    left.markdown('<h1 class="page-h1">问古籍</h1>', unsafe_allow_html=True)
    if right.button("新对话", key="qa_new", use_container_width=False):
        st.session_state["qa_messages"] = []
        st.session_state.pop("qa_pending", None)
        st.rerun()


def _handle_question(question, messages):
    question = (question or "").strip()
    if not question:
        return
    api_key = st.session_state.get("qa_key") or None
    if not has_api_key() and not api_key:
        _panel("notice", "先填一个 Key",
               "公网演示没有配置服务端 Key。展开下面的「使用自己的 DeepSeek Key」填入后就能提问。")
        return
    if has_api_key() and not api_key:
        ok, why = _quota_take()
        if not ok:
            _panel("notice", "今天的免费次数用完了", why)
            return

    history = _as_history(messages)
    messages.append({"role": "user", "content": question})
    _render_user(question)
    started = _time.perf_counter()
    try:
        with st.spinner("正在四十五部古籍里找依据…"):
            from agent import agent_answer as _agent_answer
            res = _agent_answer(question, api_key=api_key, history=history)
        res["_elapsed"] = round(_time.perf_counter() - started, 1)
    except Exception as exc:
        messages.append({
            "role": "assistant",
            "content": "回答没有生成成功。",
            "error": True,
            "detail": str(exc),
        })
        st.rerun()
    messages.append({"role": "assistant", "content": res.get("answer") or "", "meta": res})
    st.rerun()


def _ask_page():
    messages = st.session_state.setdefault("qa_messages", [])
    pending = st.session_state.pop("qa_pending", None)

    if not messages:
        _empty_state()
    else:
        _chat_title()

    if messages:
        for idx, msg in enumerate(messages):
            if msg.get("role") == "user":
                _render_user(msg.get("content") or "")
            else:
                with st.chat_message("assistant"):
                    _render_answer(msg, idx)

    api_key = _key_panel()
    ready = bool(has_api_key() or api_key)
    typed = st.chat_input(
        "问一个古籍里的问题…" if ready else "填入自己的 Key 后就能提问",
        key="qa_input",
        disabled=not ready,
    )
    _handle_question(pending or typed, messages)


# ---------- 八字 ----------

PILLARS = ("年柱", "月柱", "日柱", "时柱")

# 五行配色：不追求鲜艳，只要在纸色上能一眼分出五行即可。
WX_COLOR = {"木": "#3f7a4f", "火": "#a8392c", "土": "#96702f",
            "金": "#8a8378", "水": "#2f5b86"}
GAN_WX = {"甲": "木", "乙": "木", "丙": "火", "丁": "火", "戊": "土",
          "己": "土", "庚": "金", "辛": "金", "壬": "水", "癸": "水"}
ZHI_WX = {"寅": "木", "卯": "木", "巳": "火", "午": "火", "申": "金",
          "酉": "金", "亥": "水", "子": "水", "辰": "土", "戌": "土",
          "丑": "土", "未": "土"}


def _txt(v):
    """支神有的是 list（地支藏干各自一个十神），有的库版本给逗号串，统一成顿号。"""
    if isinstance(v, (list, tuple)):
        return "、".join(str(x) for x in v)
    return str(v or "").replace(",", "、").replace("，", "、")


def _colored(ch, table):
    color = WX_COLOR.get(table.get(ch, ""), "inherit")
    return '<span style="color:%s">%s</span>' % (color, ch)


def _bazi_chart(chart):
    """命盘图：四柱竖排成一张盘，日柱高亮。"""
    sizhu = chart["sizhu"]

    def cols(fn, cls=""):
        out = []
        for i, name in enumerate(PILLARS):
            out.append('<div class="%s%s">%s</div>' % (
                cls, " day" if i == 2 else "", fn(name)))
        return "".join(out)

    rows = ['<div class="rowlabel"></div>' + cols(lambda n: n, "pillarhead")]

    def push(label, fn, cls=""):
        rows.append('<div class="rowlabel">%s</div>' % label)
        rows.append(cols(fn, cls))

    push("十神", lambda n: chart["shishen_gan"].get(n) or "—")
    push("天干", lambda n: _colored(sizhu.get(n, "")[:1], GAN_WX), "gan")
    push("地支", lambda n: _colored(sizhu.get(n, "")[1:2], ZHI_WX), "zhi")
    push("藏干", lambda n: "、".join(chart["canggan"].get(n) or []) or "—")
    push("支神", lambda n: _txt(chart["shishen_zhi"].get(n)) or "—")
    push("纳音", lambda n: chart["nayin"].get(n) or "—")
    push("旬空", lambda n: chart["xunkong"].get(n) or "—")
    return '<div class="chart"><div class="chart-grid">%s</div></div>' % "".join(rows)


def _wuxing_bar(chart):
    """八字的五行比例条 + 图例（只数八个字，和 paipan 的口径一致）。"""
    wx = chart["wuxing"]
    total = sum(wx.values()) or 1
    segs = "".join(
        '<span style="width:%.2f%%;background:%s"></span>' % (v / total * 100, WX_COLOR[k])
        for k, v in wx.items() if v
    )
    legend = "".join(
        '<span style="color:%s">■</span>&nbsp;%s %d&nbsp;&nbsp;&nbsp;' % (WX_COLOR[k], k, v)
        for k, v in wx.items()
    )
    miss = chart.get("wuxing_missing") or []
    tail = '&nbsp;&nbsp;<span style="color:#8c2f26">缺 %s</span>' % "、".join(miss) if miss else ""
    return ('<div class="wxbar">%s</div><div class="note">%s%s</div>' % (segs, legend, tail))


def _dayun_strip(chart):
    """大运横排，当前大运描红。比表格好读：一眼看出走到第几步。"""
    cur = chart.get("current_dayun") or {}
    pills = []
    for d in chart["dayun"]:
        now = (d["ganzhi"] == cur.get("ganzhi")
               and d["start_year"] == cur.get("start_year")) if cur else False
        pills.append(
            '<div class="pill%s"><div class="gz">%s</div><div class="yr">%d · %d岁</div></div>'
            % (" cur" if now else "", d["ganzhi"], d["start_year"], d["start_age"]))
    return '<div class="dayun">%s</div>' % "".join(pills)


def _read_block(chart, key):
    """排完盘后的问答区。

    盘面本身是算出来的，不花钱；解读才调模型。所以这里先让用户把问题问清楚，
    再点一次按钮花一次调用。
    """
    qkey = key + "_q"
    pending = key + "_pending"
    if pending in st.session_state:
        st.session_state[qkey] = st.session_state.pop(pending)
    st.session_state.setdefault(qkey, "")

    st.markdown('<div class="section-label">想问什么</div>', unsafe_allow_html=True)
    st.text_input("想问什么", key=qkey, label_visibility="collapsed",
                  placeholder="例如：今年适合换工作吗？感情上要注意什么？")
    cols = st.columns(len(TOPIC_PROMPTS), gap="small")
    for i, (label, prompt) in enumerate(TOPIC_PROMPTS):
        if cols[i].button(label, key="%s_t%d" % (key, i), use_container_width=True):
            st.session_state[pending] = prompt
            st.rerun()

    server_key = has_api_key()
    api_key = None
    if not server_key:
        with st.expander("使用自己的 DeepSeek Key", expanded=True):
            st.caption("公网演示没有配置服务端 Key。Key 只用于本次会话，不写日志、不落盘。")
            api_key = st.text_input("DeepSeek API Key", type="password",
                                    key=key + "_key", label_visibility="collapsed",
                                    placeholder="sk-…") or None

    if not st.button("生成解读", type="primary", key=key + "_go"):
        return
    if not (server_key or api_key):
        st.warning("没有可用的 Key：先填入自己的 DeepSeek Key，再点一次。")
        return
    if server_key:  # 服务端 key 才计额度；访客自带 key 花的是他自己的钱
        ok, why = _quota_take()
        if not ok:
            st.warning(why)
            return

    with st.spinner("正在解读盘面…"):
        try:
            res = read(chart, question=st.session_state.get(qkey) or None, api_key=api_key)
        except Exception as exc:
            st.error("解读失败：%s" % exc)
            return
    if res["summary"]:
        st.markdown('<div class="panel panel-note"><div class="panel-body">%s</div></div>'
                    % _esc(res["summary"]), unsafe_allow_html=True)
    for sec in res["sections"]:
        st.markdown('<div class="section-label">%s</div>' % _esc(sec["title"]),
                    unsafe_allow_html=True)
        st.markdown(sec["content"])
    st.caption(res["disclaimer"])


def _bazi_view():
    st.markdown('<div class="section-label">出生信息</div>', unsafe_allow_html=True)
    with st.form("bazi_form"):
        col1, col2, col3 = st.columns(3)
        d = col1.date_input("出生日期", value=date(2000, 1, 1),
                            min_value=date(1900, 1, 1), key="bazi_d")
        t = col2.time_input("出生时间（不确定就填 12:00）", value=time(12, 0), key="bazi_t")
        gender = col3.selectbox("性别", ["male", "female"],
                                format_func=lambda g: "男" if g == "male" else "女",
                                key="bazi_g")
        submitted = st.form_submit_button("排盘", type="primary")
    st.caption("按出生地当地时间排，节气与干支由历法库计算；同一份输入永远得到同一个盘。")

    if submitted:
        try:
            st.session_state["bazi_chart"] = paipan(
                d.year, d.month, d.day, t.hour, t.minute, gender
            )
        except ValueError as exc:
            st.error(str(exc))
            st.session_state.pop("bazi_chart", None)

    chart = st.session_state.get("bazi_chart")
    if not chart:
        return

    st.markdown('<h2 class="result-h2">你的八字盘</h2>', unsafe_allow_html=True)
    st.markdown(_bazi_chart(chart), unsafe_allow_html=True)
    st.caption("日柱为命主本体，底色标红；干支按五行着色（木绿 火赤 土黄 金灰 水蓝）。")

    info = chart["input"]
    st.markdown(_chips([
        "公历 %s" % info["solar"], "农历 %s" % info["lunar"],
        "日主 %s" % chart["day_master"], "生肖 %s" % chart["shengxiao"],
    ]), unsafe_allow_html=True)

    layout = st.columns([0.55, 0.45], gap="large")
    with layout[0]:
        st.markdown(
            '<div class="card"><div class="section-label">五行分布</div>%s</div>'
            % _wuxing_bar(chart), unsafe_allow_html=True)
    with layout[1]:
        qiyun = chart["qiyun"]
        st.markdown(
            '<div class="card"><div class="section-label">起运</div>'
            '<div class="big-value">%d 年 %d 个月</div>'
            '<div class="note">%s，出生后 %d 年 %d 个月 %d 天起运</div></div>' % (
                qiyun["years"], qiyun["months"],
                "顺排" if qiyun["forward"] else "逆排",
                qiyun["years"], qiyun["months"], qiyun["days"]),
            unsafe_allow_html=True)

    if chart["dayun"]:
        cap = ""
        if chart.get("current_dayun"):
            cur = chart["current_dayun"]
            cap = ('<div class="note">红框为当前大运：%s（%d 岁起，%d 年起运）</div>'
                   % (cur["ganzhi"], cur["start_age"], cur["start_year"]))
        st.markdown(
            '<div class="card"><div class="section-label">大运</div>%s%s</div>'
            % (_dayun_strip(chart), cap), unsafe_allow_html=True)

    with st.expander("排盘明细与原始数据"):
        st.markdown(_chips([
            "命宫 %s" % chart["minggong"], "胎元 %s" % chart["taiyuan"],
            "身宫 %s" % chart["shengong"],
        ] + ["旬空 %s %s" % (k, v) for k, v in chart["xunkong"].items()]),
            unsafe_allow_html=True)
        st.code(format_bazi(chart), language=None)
        st.json(chart)

    st.markdown('<div class="soft-rule"></div>', unsafe_allow_html=True)
    _read_block(chart, "bazi_read")


# ---------- 星盘 ----------

def _astro_wheel(chart, size=440):
    """本命盘圆盘。上升点固定在左侧（盘面 9 点方向）。"""
    import math

    asc_lon = chart["asc"]["lon"]
    cx = cy = size / 2.0
    r_out = size / 2.0 - 26
    r_sign = r_out - 34
    r_planet = r_sign - 44

    def pt(lon, r):
        a = math.radians(180.0 - (lon - asc_lon))
        return cx + r * math.cos(a), cy + r * math.sin(a)

    p = ['<svg viewBox="0 0 %d %d" width="100%%" style="max-width:440px;display:block;margin:0 auto" '
         'xmlns="http://www.w3.org/2000/svg">' % (size, size)]
    p.append('<circle cx="%g" cy="%g" r="%g" fill="#fff" stroke="#e6e0d4"/>' % (cx, cy, r_out))
    p.append('<circle cx="%g" cy="%g" r="%g" fill="none" stroke="#e6e0d4"/>' % (cx, cy, r_sign))

    for i in range(12):
        lon = i * 30.0
        x1, y1 = pt(lon, r_sign)
        x2, y2 = pt(lon, r_out)
        p.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#e6e0d4"/>'
                 % (x1, y1, x2, y2))
        mx, my = pt(lon + 15, (r_sign + r_out) / 2.0)
        p.append('<text x="%.1f" y="%.1f" font-size="12" fill="#6e685e" '
                 'text-anchor="middle" dominant-baseline="middle">%s</text>'
                 % (mx, my, SIGNS[i]))

    for label, lon in (("ASC", asc_lon), ("MC", chart["mc"]["lon"])):
        x1, y1 = pt(lon, r_sign)
        x2, y2 = pt(lon, r_out)
        p.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#96322a" '
                 'stroke-width="2"/>' % (x1, y1, x2, y2))
        lx, ly = pt(lon, r_sign - 18)
        p.append('<text x="%.1f" y="%.1f" font-size="10" fill="#96322a" '
                 'text-anchor="middle" dominant-baseline="middle">%s</text>'
                 % (lx, ly, label))

    # 星体挤在一起会叠字：按两串标签的字宽判断，挤了的往内圈退一层，最多三层。
    placed = []
    for body in sorted(chart["planets"], key=lambda x: x["lon"] % 360):
        lon = body["lon"] % 360
        label = body["name"] + ("ᴿ" if body["retrograde"] else "")
        ring = 0
        while ring < 3 and any(
            same_ring == ring
            and abs(((lon - other + 180.0) % 360.0) - 180.0) < (len(label) + len(other_label)) * 3.0 + 0.8
            for other, same_ring, other_label in placed
        ):
            ring += 1
        placed.append((lon, ring, label))
        x, y = pt(lon, r_planet - ring * 26)
        tx, ty = pt(lon, r_sign - 2)
        p.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#d8d1c3" '
                 'stroke-dasharray="2 3"/>' % (x, y, tx, ty))
        p.append('<text x="%.1f" y="%.1f" font-size="11" fill="#1c1a16" '
                 'text-anchor="middle" dominant-baseline="middle" '
                 'style="paint-order:stroke;stroke:#faf8f3;stroke-width:3px">%s</text>'
                 % (x, y, label))

    p.append("</svg>")
    return "".join(p)


def _astro_view():
    st.markdown('<div class="section-label">出生信息</div>', unsafe_allow_html=True)
    with st.form("astro_form"):
        col1, col2, col3 = st.columns(3)
        d = col1.date_input("出生日期", value=date(2000, 1, 1),
                            min_value=date(1900, 1, 1), key="as_d")
        t = col2.time_input("出生时间", value=time(12, 0), key="as_t")
        city = col3.selectbox("出生城市", list(CITIES) + ["其他（手填经纬度）"], key="as_c")
        if city == "其他（手填经纬度）":
            c1, c2, c3 = st.columns(3)
            lat = c1.number_input("纬度（北纬为正）", value=39.90, format="%.2f")
            lon = c2.number_input("经度（东经为正）", value=116.40, format="%.2f")
            tz = c3.number_input("时区偏移", value=8.0, format="%.1f")
        else:
            lat, lon = CITIES[city]
            tz = 8.0
        submitted = st.form_submit_button("排盘", type="primary")
    st.caption("地心视黄经、整宫制。出生时间越准，上升和宫位越准——差 2 小时上升会偏一个星座。")

    if submitted:
        try:
            st.session_state["astro_chart"] = natal_chart(
                d.year, d.month, d.day, t.hour, t.minute, tz, lat, lon, city
            )
        except ValueError as exc:
            st.error(str(exc))
            st.session_state.pop("astro_chart", None)

    chart = st.session_state.get("astro_chart")
    if not chart:
        return

    st.markdown('<h2 class="result-h2">你的本命盘</h2>', unsafe_allow_html=True)
    asc, mc = chart["asc"], chart["mc"]
    wheel, info = st.columns([0.58, 0.42], gap="large")
    with wheel:
        st.markdown('<div class="card astro-card">%s</div>' % _astro_wheel(chart),
                    unsafe_allow_html=True)
        st.caption("上升点固定在盘面左侧，逆时针为黄经增加方向；虚线指向星体所在黄经。")
    with info:
        st.markdown(
            '<div class="card">'
            '<div class="pillar"><div class="label">上升 ASC</div>'
            '<div class="ganzhi">%s</div><div class="meta">%s°</div></div>'
            '<div class="pillar"><div class="label">天顶 MC</div>'
            '<div class="ganzhi">%s</div><div class="meta">%s°</div></div>'
            '%s</div>' % (
                asc["sign"], asc["degree"], mc["sign"], mc["degree"],
                _chips(["%s %d" % (k, v) for k, v in chart["elements"].items()] +
                       ["%s %d" % (k, v) for k, v in chart["modalities"].items()])),
            unsafe_allow_html=True)

    with st.expander("星体位置、相位与原始数据"):
        st.dataframe(
            [{"星体": p["name"], "星座": p["sign"], "度数": p["degree"],
              "逆行": "逆" if p["retrograde"] else ""} for p in chart["planets"]],
            hide_index=True, use_container_width=True)
        if chart.get("aspects"):
            st.dataframe(chart["aspects"], hide_index=True, use_container_width=True)
        st.code(format_chart(chart), language=None)
        st.json(chart)

    st.markdown('<div class="soft-rule"></div>', unsafe_allow_html=True)
    _read_block(chart, "astro_read")


# ---------- 塔罗 ----------

def _tarot_view():
    st.markdown('<div class="section-label">抽牌</div>', unsafe_allow_html=True)
    with st.form("tarot_form"):
        col1, col2 = st.columns(2)
        spread = col1.selectbox("牌阵", list(SPREADS),
                                format_func=lambda k: SPREADS[k][0], key="tt_s")
        seed_text = col2.text_input("固定种子（可留空，填了结果可复现）", key="tt_seed")
        submitted = st.form_submit_button("抽牌", type="primary")
    st.caption("抽到什么是随机的；怎么解释才是塔罗真正在做的部分，别反复抽到满意为止。")

    if submitted:
        seed = None
        if seed_text.strip():
            try:
                seed = int(seed_text.strip())
            except ValueError:
                st.warning("种子要是整数，这次按随机处理")
        st.session_state["tarot_chart"] = draw_tarot(seed=seed, spread=spread)

    chart = st.session_state.get("tarot_chart")
    if not chart:
        return

    st.markdown('<h2 class="result-h2">你抽到的牌</h2>', unsafe_allow_html=True)
    cards = chart["cards"]
    cols = st.columns(min(len(cards), 3), gap="small")
    for i, card in enumerate(cards):
        cols[i % len(cols)].markdown(
            '<div class="card tarot-card">'
            '<div class="section-label">%s</div>'
            '<div class="tarot-name">%s</div>'
            '<div class="meta"><em>%s</em> · %s</div>'
            '<div class="note">%s</div></div>' % (
                _esc(card["position"]), _esc(card["name"]), _esc(card["orientation"]),
                _esc(card["arcana"]), _esc(card["meaning"])),
            unsafe_allow_html=True)

    with st.expander("牌面明细与原始数据"):
        st.code(format_draw(cards), language=None)
        st.json(chart)

    st.markdown('<div class="soft-rule"></div>', unsafe_allow_html=True)
    _read_block(chart, "tarot_read")


def _fortune_page():
    st.markdown(
        '<div class="page-head"><h1 class="page-h1">排一张盘</h1>'
        '<p class="page-sub">先把盘排出来，排盘本身不花钱；解读才会调用模型。</p></div>',
        unsafe_allow_html=True,
    )
    tools = ["八字", "星盘", "塔罗"]
    tool = st.selectbox("排盘方式", tools, index=0, key="fortune_tool")
    if tool == "八字":
        _bazi_view()
    elif tool == "星盘":
        _astro_view()
    else:
        _tarot_view()


# ---------- 内部工具（默认隐藏） ----------

def _human_bytes(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "—"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%.1f %s" % (n, unit)).replace(".0 ", " ")
        n /= 1024


def _status_cn(s):
    return {"pass": "通过", "warn": "警告", "fail": "失败"}.get(s, s or "—")


def _data_tab():
    import datahub

    st.caption("登记语料 / chunk / embedding 的版本、血缘和质量门。"
               "库是单文件 SQLite，部署时用 MINGLI_PLATFORM_DB 指到持久化目录。")

    latest = datahub.latest()
    c1, c2 = st.columns([0.72, 0.28])
    with c2:
        if st.button("重新扫描并登记", type="primary", use_container_width=True, key="dh_scan"):
            with st.spinner("扫描语料与 embedding，计算 sha256…"):
                try:
                    datahub.scan_and_store()
                except Exception as exc:
                    st.error("扫描失败：{}".format(exc))
                else:
                    st.rerun()

    if not latest:
        st.info("还没有登记过数据版本。点右上角「重新扫描并登记」。")
        return

    with c1:
        st.markdown(
            '<div class="section-label">当前版本 · %s</div>'
            '<div class="note">登记于 %s</div>' % (
                latest["version"], (latest["scanned_at"] or "").replace("T", " ")),
            unsafe_allow_html=True,
        )
        m1, m2, m3 = st.columns(3)
        m1.metric("书目", latest["books"])
        m2.metric("chunk", "{:,}".format(latest["chunks"]))
        m3.metric("字数", "{:,}".format(latest["chars"]))

    checks = datahub.checks_for(latest["id"])
    bad = sum(1 for c in checks if c["status"] == "fail")
    warn = sum(1 for c in checks if c["status"] == "warn")
    st.markdown('<div class="section-label" style="margin-top:1rem">质量门 · %d 通过 / %d 警告 / %d 失败</div>'
                % (len(checks) - bad - warn, warn, bad), unsafe_allow_html=True)
    st.dataframe(
        [{"检查": c["check_name"], "结果": _status_cn(c["status"]),
          "值": c["value"], "说明": c["detail"]} for c in checks],
        hide_index=True, use_container_width=True,
    )

    st.markdown('<div class="section-label" style="margin-top:1rem">资产与哈希</div>',
                unsafe_allow_html=True)
    assets = datahub.assets_for(latest["id"])
    st.dataframe(
        [{"类型": a["kind"], "文件": a["path"], "大小": _human_bytes(a["bytes"]),
          "sha256": (a["sha256"] or "")[:16]} for a in assets],
        hide_index=True, use_container_width=True,
    )

    hist = datahub.history(limit=10)
    if len(hist) > 1:
        with st.expander("版本历史（%d）" % len(hist), expanded=False):
            st.dataframe(
                [{"id": h["id"], "版本": h["version"], "书目": h["books"],
                  "chunk": h["chunks"], "字数": h["chars"],
                  "登记时间": h["scanned_at"]} for h in hist],
                hide_index=True, use_container_width=True,
            )


def _run_metric_text(r):
    m = r["metrics"]
    if r["suite"] == "retrieval":
        val = m.get("line_recall")
        return "—" if val is None else "R@5 {:.1f}%".format(val * 100)
    if r["suite"] == "agent":
        return "通过 {}/{}".format(m.get("auto_pass"), m.get("total"))
    if r["suite"] == "refusal":
        val = m.get("refusal_accuracy")
        return "—" if val is None else "拒答正确 {:.0f}%".format(val * 100)
    return "—"


def _suite_cn(s):
    return {"retrieval": "检索", "agent": "Agent", "refusal": "拒答"}.get(s, s or "—")


def _version_text(v):
    return "未记录" if not v or str(v).startswith("imported:") else v


def _run_label(r):
    return "#%d · %s · %s · %s" % (r["id"], r["suite"], r["name"], _run_metric_text(r))


def _eval_tab():
    import evalhub

    st.caption("把每次评测登记成带配置、数据集版本和逐题明细的 run；"
               "两次 run 可以直接比，掉点超过阈值判回归失败。")

    runs = evalhub.list_runs(limit=200)
    by_suite = {}
    for r in runs:
        by_suite.setdefault(r["suite"], r)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("登记 run", len(runs))
    ret = next((r for r in runs if r["source"] == "results_8681_tuned.csv#rrf"),
               by_suite.get("retrieval"))
    c2.metric("检索 R@5（当前基线）", "—" if not ret or ret["metrics"].get("line_recall") is None
              else "%.1f%%" % (ret["metrics"]["line_recall"] * 100))
    multi = [r for r in runs if r["suite"] == "agent" and r["backend"] == "multi"]
    if multi:
        vals = [r["metrics"].get("pass_rate") for r in multi
                if r["metrics"].get("pass_rate") is not None]
        total = multi[0]["metrics"].get("total") or 15
        c3.metric("多 Agent 通过（均值）",
                  "%.1f / %s" % (sum(vals) / len(vals) * total, total) if vals else "—")
    else:
        ag = by_suite.get("agent")
        c3.metric("Agent 通过（最近登记）", "—" if not ag else "%s/%s" % (
            ag["metrics"].get("auto_pass"), ag["metrics"].get("total")))
    rf = by_suite.get("refusal")
    c4.metric("拒答正确（最近登记）", "—" if not rf or rf["metrics"].get("refusal_accuracy") is None
              else "%.0f%%" % (rf["metrics"]["refusal_accuracy"] * 100))

    with st.expander("运行与导入", expanded=not runs):
        b1, b2 = st.columns([0.45, 0.55])
        with b1:
            if st.button("导入 eval/ 下已有结果", use_container_width=True, key="eh_import"):
                with st.spinner("读 results_agent_*.json / *results*.csv…"):
                    added, skipped, errors = evalhub.import_existing()
                if errors:
                    st.warning("导入 {} 个，跳过 {} 个；{} 个失败".format(added, skipped, len(errors)))
                    st.code("\n".join(errors))
                else:
                    st.success("导入 {} 个，跳过 {} 个".format(added, skipped))
                st.rerun()
            st.caption("已有的 6 次 Agent run、9 次检索 run 和 1 次拒答 run 可直接入库。")

        with b2:
            with st.form("eh_run_retrieval"):
                f1, f2, f3 = st.columns([0.34, 0.33, 0.33])
                mode = f1.selectbox("检索策略", ["rrf", "bm25", "dense"], index=0)
                top_k = f2.slider("Top-k", 1, 10, 5)
                limit = f3.number_input("只跑前 N 条（0=全量）", 0, 200, 0)
                run_now = st.form_submit_button("跑一次检索评测", type="primary")
            if run_now:
                with st.spinner("加载 BGE-M3 并逐题检索；首次可能要一两分钟…"):
                    try:
                        rid = evalhub.run_retrieval(mode=mode, top_k=top_k, limit=limit)
                    except Exception as exc:
                        st.error("评测失败：{}".format(exc))
                    else:
                        st.success("已登记 run #%d" % rid)
                        st.rerun()

    if not runs:
        st.info("还没有 run。先导入已有结果，或跑一次检索评测。")
        return

    st.markdown('<div class="section-label" style="margin-top:1rem">Run 账本</div>',
                unsafe_allow_html=True)
    st.dataframe(
        [{"编号": r["id"], "登记时间": r["created_at"], "套件": _suite_cn(r["suite"]),
          "后端": r["backend"], "数据集": _version_text(r["dataset_version"]),
          "关键指标": _run_metric_text(r), "名称": r["name"]} for r in runs],
        hide_index=True, use_container_width=True,
    )

    st.markdown('<div class="section-label" style="margin-top:1rem">逐题明细</div>',
                unsafe_allow_html=True)
    run_id = st.selectbox("选择一个 run", [r["id"] for r in runs],
                          format_func=lambda i: _run_label(next(r for r in runs if r["id"] == i)),
                          key="eh_case_run")
    cases = evalhub.cases_for(run_id)
    st.dataframe(
        [{"id": c["case_id"], "类别": c["category"],
          "可答": "是" if c["answerable"] else "否",
          "通过": "—" if c["passed"] is None else ("通过" if c["passed"] else "未通过"),
          "Recall": "—" if c["recall"] is None else "%.2f" % c["recall"],
          "MRR": "—" if c["mrr"] is None else "%.2f" % c["mrr"],
          "耗时(ms)": "—" if c["latency_ms"] is None else "%.0f" % c["latency_ms"],
          "问题": (c["question"] or "")[:60]} for c in cases],
        hide_index=True, use_container_width=True,
    )
    if cases:
        cid = st.selectbox("查看单题", [c["case_id"] for c in cases], key="eh_case_one")
        case = next(c for c in cases if c["case_id"] == cid)
        st.markdown("**问题**：" + (case["question"] or ""))
        if case["output"]:
            st.markdown("**输出**：" + case["output"][:2000])
        if case["citations"]:
            st.markdown(_chips([str(x) for x in case["citations"]], seal=True),
                        unsafe_allow_html=True)
        if case["detail"]:
            with st.expander("判据 / 原始明细", expanded=False):
                st.json(case["detail"])

    st.markdown('<div class="section-label" style="margin-top:1rem">版本对比 / 回归门</div>',
                unsafe_allow_html=True)
    suites = [s for s in ("retrieval", "agent", "refusal") if any(r["suite"] == s for r in runs)]
    suite = st.selectbox("对比哪一类", suites, key="eh_cmp_suite")
    candidates = [r for r in runs if r["suite"] == suite]
    if len(candidates) < 2:
        st.info("这一类至少要有两次 run 才能对比。")
        return
    b1, b2 = st.columns(2)
    base = b1.selectbox("基线", [r["id"] for r in candidates],
                        format_func=lambda i: _run_label(next(r for r in candidates if r["id"] == i)),
                        key="eh_base")
    cand = b2.selectbox("候选", [r["id"] for r in candidates],
                        format_func=lambda i: _run_label(next(r for r in candidates if r["id"] == i)),
                        key="eh_cand")
    if base == cand:
        st.warning("基线和候选是同一个 run。")
        return
    res = evalhub.compare(base, cand)
    if res["status"] == "fail":
        st.error("回归门：失败（%s 下降超过 %.0f%%）" % (
            res.get("gate_metric"), (res.get("threshold") or 0) * 100))
    elif res["status"] == "pass":
        st.success("回归门：通过（%s 未下降超过 %.0f%%）" % (
            res.get("gate_metric"), (res.get("threshold") or 0) * 100))
    else:
        st.warning("回归门：%s" % res.get("reason", "无法判定"))
    if res["checks"]:
        st.dataframe(
            [{"指标": c["metric"], "基线": round(c["baseline"], 4),
              "候选": round(c["candidate"], 4), "变化": round(c["delta"], 4),
              "门禁": _status_cn(c["status"])} for c in res["checks"]],
            hide_index=True, use_container_width=True,
        )


def _admin_page():
    st.markdown(
        '<div class="page-head"><h1 class="page-h1">维护</h1>'
        '<p class="page-sub">内部工具：数据版本与评测账本，不对访客展示。</p></div>',
        unsafe_allow_html=True,
    )
    t1, t2 = st.tabs(["数据中台", "评测中台"])
    with t1:
        _data_tab()
    with t2:
        _eval_tab()


def main():
    st.set_page_config(
        page_title="问古 · 古籍问答",
        page_icon="📜",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    st.markdown(CSS, unsafe_allow_html=True)

    view = _header()
    if view == "排盘":
        _fortune_page()
    elif view == "维护":
        _admin_page()
    else:
        _ask_page()


if __name__ == "__main__":
    main()
