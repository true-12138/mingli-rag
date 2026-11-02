# -*- coding: utf-8 -*-
"""命理古籍问答 · 排盘：Streamlit 界面。

设计上刻意只做「宣纸 + 墨色 + 朱砂」三种颜色：
- 底色是纸，正文是墨，强调色只给按钮和引用标记，避免把古籍界面做得花哨。
- 八字渲染成一张命盘图（四柱竖排 + 五行比例条 + 大运横排），
  星盘画成圆盘（上升定在左侧），排盘结果先给图再给文字。

功能与旧版一致：古籍问答（三种检索策略）、八字、星盘、塔罗，四个页签。
"""
import json
import os
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

import streamlit as st

# 无论从仓库根目录还是 src/ 内部启动，都能找到同级模块
sys.path.append(str(Path(__file__).resolve().parent))

from fortune.astro import SIGNS, format_chart, natal_chart
from fortune.bazi import format_bazi, paipan
from fortune.interpret import has_api_key, read
from fortune.tarot import SPREADS, draw as draw_tarot
from fortune.tarot import format_draw
from rag import answer

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

EXAMPLES = (
    "七杀和偏官是同一个神吗？",
    "伤官见官，为祸百端，是不是一定不好？",
    "纳音五行和正五行，谁说了算？",
)

CSS = """
<style>
:root {
  --paper: #faf7f1;
  --paper-2: #f2ece1;
  --ink: #201b16;
  --ink-soft: #5b5348;
  --seal: #8c2f26;
  --rule: #ddd3c2;
}
html, body, [class*="css"] {
  font-family: "Songti SC", "STSong", "Noto Serif SC", "Source Han Serif SC", serif;
}
.stApp { background: var(--paper); }

/* 顶部装饰条 */
.stApp::before {
  content: "";
  position: fixed; top: 0; left: 0; right: 0; height: 3px;
  background: linear-gradient(90deg, var(--seal), #c98a4b 55%, transparent);
  z-index: 999;
}
[data-testid="stHeader"] { background: transparent; }

/* 标题区 */
.hero { padding: 1.2rem 0 1.4rem; border-bottom: 1px solid var(--rule); margin-bottom: 1.4rem; }
.hero h1 {
  font-size: 2.35rem; line-height: 1.25; margin: 0 0 .45rem;
  letter-spacing: .12em; color: var(--ink); font-weight: 700;
}
.hero .sub { color: var(--ink-soft); font-size: .98rem; letter-spacing: .04em; }
.hero .sub b { color: var(--seal); font-weight: 600; }
.stats { margin-top: 1rem; display: flex; gap: .6rem; flex-wrap: wrap; }
.stat {
  border: 1px solid var(--rule); background: #fff; border-radius: 999px;
  padding: .28rem .86rem; font-size: .85rem; color: var(--ink-soft);
}
.stat b { color: var(--ink); font-size: 1rem; margin-right: .3rem; }

/* 卡片 */
[data-testid="stVerticalBlockBorderWrapper"] {
  background: #fff; border-radius: 14px;
  border: 1px solid var(--rule) !important;
  box-shadow: 0 1px 2px rgba(32,27,22,.04);
}

/* 页签 */
.stTabs [data-baseweb="tab-list"] { gap: 1.6rem; border-bottom: 1px solid var(--rule); }
.stTabs [data-baseweb="tab"] {
  height: 2.9rem; background: transparent; padding: 0 .1rem;
  font-size: 1rem; letter-spacing: .08em; color: var(--ink-soft);
}
.stTabs [aria-selected="true"] { color: var(--seal) !important; font-weight: 600; }
.stTabs [data-baseweb="tab-highlight"] { background: var(--seal); height: 2px; }

/* 按钮 */
.stButton > button, .stFormSubmitButton > button {
  border-radius: 8px; border: 1px solid var(--seal);
  background: var(--seal); color: #fff; letter-spacing: .08em;
  padding: .42rem 1.1rem; transition: all .15s ease;
}
.stButton > button:hover, .stFormSubmitButton > button:hover {
  background: #741f18; border-color: #741f18; color: #fff;
}
.stButton > button:focus { box-shadow: 0 0 0 2px rgba(140,47,38,.18); }

/* 输入框 */
.stTextInput input, .stNumberInput input { background: #fff; border-radius: 8px; }

/* 四柱 */
.pillars { display: flex; gap: .8rem; margin: .4rem 0 1rem; flex-wrap: wrap; }
.pillar {
  flex: 1 1 0; min-width: 130px; background: #fff; border: 1px solid var(--rule);
  border-radius: 12px; padding: .9rem .6rem; text-align: center;
}
.pillar .label { font-size: .8rem; color: var(--ink-soft); letter-spacing: .18em; }
.pillar .ganzhi {
  font-size: 1.85rem; letter-spacing: .14em; color: var(--ink);
  margin: .35rem 0 .3rem; font-weight: 600; white-space: nowrap;
}
.pillar .meta { font-size: .8rem; color: var(--ink-soft); line-height: 1.6; }
.pillar .meta em { font-style: normal; color: var(--seal); }

/* 标签 */
.chips { display: flex; flex-wrap: wrap; gap: .4rem; }
.chip {
  display: inline-block; padding: .2rem .62rem; border-radius: 6px;
  background: var(--paper-2); color: var(--ink-soft);
  font-size: .82rem; border: 1px solid var(--rule);
}
.chip.seal { background: #f7e9e6; border-color: #e3c4be; color: var(--seal); }

/* 回答正文 */
.answer { font-size: 1.02rem; line-height: 1.95; color: var(--ink); }
.answer p { margin: .55rem 0; }
.answer blockquote {
  border-left: 3px solid var(--seal); background: var(--paper-2);
  margin: .8rem 0; padding: .55rem .9rem; color: var(--ink-soft);
}
.section-title {
  font-size: .82rem; letter-spacing: .2em; color: var(--ink-soft);
  text-transform: uppercase; margin: .2rem 0 .6rem;
}
.note { color: var(--ink-soft); font-size: .85rem; }

/* 命盘图 */
.chart { border: 1px solid var(--rule); border-radius: 14px; overflow: hidden; background: #fff; }
.chart-grid { display: grid; grid-template-columns: 78px repeat(4, 1fr); }
.chart-grid > div {
  padding: .5rem .35rem; text-align: center; border-bottom: 1px solid var(--rule);
  font-size: .85rem; color: var(--ink-soft);
}
.chart-grid .rowlabel {
  text-align: right; padding-right: .75rem; background: var(--paper-2);
  letter-spacing: .12em; font-size: .75rem;
}
.chart-grid .pillarhead { font-size: .8rem; letter-spacing: .22em; color: var(--ink); }
.chart-grid .gan, .chart-grid .zhi { font-size: 1.65rem; font-weight: 600; line-height: 1.3; }
.chart-grid .day { background: #fbf3f1; }
.chart-grid .lbl-day { color: var(--seal); }

/* 五行比例条 */
.wxbar { display: flex; height: 10px; border-radius: 999px; overflow: hidden;
         background: var(--paper-2); margin: .35rem 0 .55rem; }
.wxbar span { display: block; height: 100%; }

/* 大运 */
.dayun { display: flex; gap: .45rem; overflow-x: auto; padding-bottom: .25rem; }
.dayun .pill {
  flex: 0 0 auto; min-width: 66px; text-align: center; background: #fff;
  border: 1px solid var(--rule); border-radius: 10px; padding: .4rem .25rem;
}
.dayun .pill.cur { border-color: var(--seal); background: #fbf3f1; }
.dayun .gz { font-size: 1.12rem; letter-spacing: .08em; color: var(--ink); }
.dayun .yr { font-size: .72rem; color: var(--ink-soft); margin-top: .15rem; }
</style>
"""


def _chips(items, seal=False):
    cls = "chip seal" if seal else "chip"
    return '<div class="chips">%s</div>' % "".join(
        '<span class="%s">%s</span>' % (cls, x) for x in items
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
        return False, "本次会话的免费解读次数已用完（%d 次）。刷新页面可重置，或填入自己的 Key。" % SESSION_LLM_LIMIT

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


def _quota_left_today():
    return max(DAILY_LLM_LIMIT - _quota_used_today(), 0)


def _quota_caption():
    if has_api_key():
        st.caption("今日全站剩余免费解读 %d 次（上限 %d）。" % (_quota_left_today(), DAILY_LLM_LIMIT))


TOPIC_PROMPTS = (
    ("感情", "请结合盘面，重点讲讲我的感情与相处方式。"),
    ("事业", "请结合盘面，重点讲讲我的事业方向与适合的工作方式。"),
    ("学业", "请结合盘面，重点讲讲我的学业与适合的学习方式。"),
    ("财运", "请结合盘面，重点讲讲我的财务倾向与用钱方式。"),
)


def _read_block(chart, key):
    """排完盘后的问答区。

    盘面本身是算出来的，不花钱；解读才调模型。所以这里先让用户把问题问清楚
    （感情/事业是绝大多数人真正想知道的），再点一次按钮花一次调用。
    公网没配服务端 Key 时，让访客填自己的 Key——key 只存在 session_state，
    不写日志、不落盘，也不会带给别的访客（Streamlit 的 session 是隔离的）。
    """
    qkey = key + "_q"
    pending = key + "_pending"
    # 话题按钮是在输入框已经渲染之后才被点中的，这时不能直接改 qkey
    # （Streamlit 不允许改动已实例化的 widget）。先写进 pending，
    # 下一次 rerun 在输入框创建之前搬过去。
    if pending in st.session_state:
        st.session_state[qkey] = st.session_state.pop(pending)
    st.session_state.setdefault(qkey, "")

    st.markdown('<div class="section-title">问自己的盘</div>', unsafe_allow_html=True)
    st.text_input("想问什么", key=qkey, label_visibility="collapsed",
                  placeholder="例如：今年适合换工作吗？感情上要注意什么？")
    cols = st.columns(len(TOPIC_PROMPTS))
    for i, (label, prompt) in enumerate(TOPIC_PROMPTS):
        if cols[i].button(label, key="%s_t%d" % (key, i), use_container_width=True):
            st.session_state[pending] = prompt
            st.rerun()

    server_key = has_api_key()
    api_key = None
    if not server_key:
        st.markdown(
            '<div class="note">公网 Demo 没有配置服务端 Key。填入自己的 DeepSeek Key '
            '只用于本次会话，不写日志、不落盘；不填也能看盘，只是不能生成解读。</div>',
            unsafe_allow_html=True)
        api_key = st.text_input("DeepSeek API Key", type="password",
                                key=key + "_key") or None

    if server_key:
        _quota_caption()

    if not st.button("生成解读", type="primary", key=key + "_go"):
        return
    if not (server_key or api_key):
        st.warning("没有可用的 Key：先在上面填入自己的 DeepSeek Key，再点一次。")
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
        st.success(res["summary"])
    for sec in res["sections"]:
        st.subheader(sec["title"])
        st.markdown(sec["content"])
    st.caption(res["disclaimer"])


# ---------- 古籍问答 ----------

def _qa_tab():
    if not st.session_state.get("qa_q"):
        st.session_state["qa_q"] = ""

    left, right = st.columns([0.62, 0.38], gap="large")

    with left:
        question = st.text_input(
            "你的问题", key="qa_q", placeholder="例如：取格以月令为主，还是以透出的天干为主？",
        )
        c1, c2 = st.columns([0.55, 0.45])
        mode = c1.radio("检索策略", ["rrf", "bm25", "dense"], index=0,
                        horizontal=True, help="rrf=语义+字面融合，bm25=精确术语，dense=语义")
        top_k = c2.slider("召回条数", min_value=1, max_value=10, value=5)
        run_btn = st.button("开始回答", type="primary")
        # 公网 Demo 不一定配了服务端 key，让访客能自带一个；只存在本次会话
        if has_api_key():
            api_key = None
            _quota_caption()
        else:
            st.markdown('<div class="note">公网未配置服务端 Key，可填自己的 DeepSeek Key'
                        '（仅本次会话，不落盘）。</div>', unsafe_allow_html=True)
            api_key = st.text_input("DeepSeek API Key", type="password", key="qa_key") or None

    with right:
        st.markdown('<div class="section-title">可以这样问</div>', unsafe_allow_html=True)
        for i, ex in enumerate(EXAMPLES):
            if st.button(ex, key="ex%d" % i, use_container_width=True):
                st.session_state["qa_q"] = ex
                st.rerun()

    st.markdown('<div class="note">仅依据入库古籍片段作答；片段只是主题相近、不能正面回答时，'
                '会明确拒答而不是硬凑。</div>', unsafe_allow_html=True)
    st.divider()

    if not run_btn:
        return
    if not question.strip():
        st.warning("请先输入问题")
        return
    if not (has_api_key() or api_key):
        st.warning("没有可用的 Key：填入自己的 DeepSeek Key 后再点一次。")
        return
    if has_api_key() and not api_key:
        ok, why = _quota_take()
        if not ok:
            st.warning(why)
            return

    with st.spinner("检索古籍 + 生成回答中；首次使用要先加载检索模型，可能需要一两分钟…"):
        try:
            res = answer(question, top_k=top_k, mode=mode, api_key=api_key)
        except Exception as exc:
            st.error("生成失败：{}".format(exc))
            st.info("排盘 / 星盘 / 塔罗不依赖检索模型，那几个页签可以正常使用。")
            st.stop()

    body, side = st.columns([0.62, 0.38], gap="large")

    with body:
        with st.container(border=True):
            st.markdown('<div class="section-title">回答</div>', unsafe_allow_html=True)
            if res["can_answer"] is False:
                st.markdown('<div class="answer">%s</div>' % res["answer"], unsafe_allow_html=True)
                if res.get("refusal_reason"):
                    st.caption("拒答理由：%s" % res["refusal_reason"])
            elif res["can_answer"] is None:
                st.error("模型输出的 JSON 解析失败")
                st.code(res.get("raw", ""), language="json")
            else:
                st.markdown(res["answer"])
                if res["invalid_citations"]:
                    st.error("发现非法引用：%s" % res["invalid_citations"])

    with side:
        with st.container(border=True):
            st.markdown('<div class="section-title">有效引用</div>', unsafe_allow_html=True)
            if res["citations_chunk_ids"]:
                st.markdown(_chips(res["citations_chunk_ids"], seal=True), unsafe_allow_html=True)
            else:
                st.markdown('<div class="note">本次无有效引用</div>', unsafe_allow_html=True)
            st.markdown('<div class="section-title" style="margin-top:1rem">本次召回</div>',
                        unsafe_allow_html=True)
            st.markdown(_chips(res["retrieved_chunk_ids"]), unsafe_allow_html=True)
            st.caption("检索策略 %s · Top-%d" % (mode, top_k))

    with st.expander("查看原始返回 JSON（调试用）"):
        st.json(res)


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
    """命盘图：四柱竖排成一张盘，日柱高亮。

    行序按传统命书的读法——十神在上，干支在中，藏干/支神在下，
    纳音和旬空是附注。用 HTML 网格而不是 st.dataframe，
    因为 df 会把「日柱」当成普通一列，丢掉它才是命主本体这层意思。
    """
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


def _bazi_tab():
    with st.container(border=True):
        st.markdown('<div class="section-title">出生信息</div>', unsafe_allow_html=True)
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

    st.markdown(_bazi_chart(chart), unsafe_allow_html=True)
    st.caption("日柱为命主本体，底色标红；干支按五行着色（木绿 火赤 土黄 金灰 水蓝）。")

    info = chart["input"]
    st.markdown(_chips([
        "公历 %s" % info["solar"], "农历 %s" % info["lunar"],
        "日主 %s" % chart["day_master"], "生肖 %s" % chart["shengxiao"],
        "命宫 %s" % chart["minggong"], "胎元 %s" % chart["taiyuan"],
        "身宫 %s" % chart["shengong"],
    ]), unsafe_allow_html=True)

    with st.container(border=True):
        st.markdown('<div class="section-title">五行分布</div>', unsafe_allow_html=True)
        st.markdown(_wuxing_bar(chart), unsafe_allow_html=True)

    qiyun = chart["qiyun"]
    with st.container(border=True):
        st.markdown('<div class="section-title">大运</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="note">%s，出生后 %d 年 %d 个月 %d 天起运</div>' % (
                "顺排" if qiyun["forward"] else "逆排",
                qiyun["years"], qiyun["months"], qiyun["days"]),
            unsafe_allow_html=True)
        if chart["dayun"]:
            st.markdown(_dayun_strip(chart), unsafe_allow_html=True)
            if chart.get("current_dayun"):
                cur = chart["current_dayun"]
                st.caption("红框为当前大运：%s（%d 岁起，%d 年起运）" % (
                    cur["ganzhi"], cur["start_age"], cur["start_year"]))
        st.markdown('<div class="section-title" style="margin-top:1rem">旬空</div>',
                    unsafe_allow_html=True)
        st.markdown(_chips(["%s %s" % (k, v) for k, v in chart["xunkong"].items()]),
                    unsafe_allow_html=True)

    with st.expander("查看完整排盘文本 / 结构化数据"):
        st.code(format_bazi(chart), language=None)
        st.json(chart)

    st.divider()
    _read_block(chart, "bazi_read")


# ---------- 星盘 ----------

def _astro_wheel(chart, size=440):
    """本命盘圆盘。

    上升点固定在左侧（盘面 9 点方向）——这是占星软件的通行画法，
    好处是同一张盘无论何时打开，宫位方向都一样，不用重新找上升。
    黄经逆时针增加；外圈是十二星座，内圈是星体。
    """
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
    p.append('<circle cx="%g" cy="%g" r="%g" fill="#fff" stroke="#ddd3c2"/>' % (cx, cy, r_out))
    p.append('<circle cx="%g" cy="%g" r="%g" fill="none" stroke="#ddd3c2"/>' % (cx, cy, r_sign))

    for i in range(12):
        lon = i * 30.0
        x1, y1 = pt(lon, r_sign)
        x2, y2 = pt(lon, r_out)
        p.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#ddd3c2"/>'
                 % (x1, y1, x2, y2))
        mx, my = pt(lon + 15, (r_sign + r_out) / 2.0)
        p.append('<text x="%.1f" y="%.1f" font-size="12" fill="#5b5348" '
                 'text-anchor="middle" dominant-baseline="middle">%s</text>'
                 % (mx, my, SIGNS[i]))

    for label, lon in (("ASC", asc_lon), ("MC", chart["mc"]["lon"])):
        x1, y1 = pt(lon, r_sign)
        x2, y2 = pt(lon, r_out)
        p.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#8c2f26" '
                 'stroke-width="2"/>' % (x1, y1, x2, y2))
        lx, ly = pt(lon, r_sign - 18)
        p.append('<text x="%.1f" y="%.1f" font-size="10" fill="#8c2f26" '
                 'text-anchor="middle" dominant-baseline="middle">%s</text>'
                 % (lx, ly, label))

    # 星体挤在一起会叠字：按「两串标签的字宽约占多少度」判断，
    # 挤了的往内圈退一层，最多退三层。写死角度阈值不行——
    # 「太阳」两个字和「海王星」三个字需要的余量差一倍。
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
        p.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#c9bfae" '
                 'stroke-dasharray="2 3"/>' % (x, y, tx, ty))
        # 描一圈纸色描边：万一一两颗星实在挤到一起，字仍然读得出来
        p.append('<text x="%.1f" y="%.1f" font-size="11" fill="#201b16" '
                 'text-anchor="middle" dominant-baseline="middle" '
                 'style="paint-order:stroke;stroke:#faf7f1;stroke-width:3px">%s</text>'
                 % (x, y, label))

    p.append("</svg>")
    return "".join(p)


def _astro_tab():
    with st.container(border=True):
        st.markdown('<div class="section-title">出生信息</div>', unsafe_allow_html=True)
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

    asc, mc = chart["asc"], chart["mc"]
    wheel, info = st.columns([0.58, 0.42], gap="large")
    with wheel:
        with st.container(border=True):
            st.markdown('<div class="section-title">本命盘</div>', unsafe_allow_html=True)
            st.markdown(_astro_wheel(chart), unsafe_allow_html=True)
            st.caption("上升点固定在盘面左侧，逆时针为黄经增加方向；"
                       "虚线指向星体所在黄经，ᴿ 为逆行。")
    with info:
        with st.container(border=True):
            st.markdown('<div class="section-title">四轴</div>', unsafe_allow_html=True)
            st.markdown('<div class="pillar"><div class="label">上升 ASC</div>'
                        '<div class="ganzhi">%s</div><div class="meta">%s°</div></div>'
                        % (asc["sign"], asc["degree"]), unsafe_allow_html=True)
            st.markdown('<div class="pillar"><div class="label">天顶 MC</div>'
                        '<div class="ganzhi">%s</div><div class="meta">%s°</div></div>'
                        % (mc["sign"], mc["degree"]), unsafe_allow_html=True)

    with st.container(border=True):
        st.markdown('<div class="section-title">星体位置</div>', unsafe_allow_html=True)
        st.dataframe(
            [{"星体": p["name"], "星座": p["sign"], "度数": p["degree"],
              "逆行": "逆" if p["retrograde"] else ""} for p in chart["planets"]],
            hide_index=True, use_container_width=True)

    c1, c2 = st.columns(2)
    with c1:
        with st.container(border=True):
            st.markdown('<div class="section-title">元素分布</div>', unsafe_allow_html=True)
            st.markdown(_chips(["%s %d" % (k, v) for k, v in chart["elements"].items()]),
                        unsafe_allow_html=True)
    with c2:
        with st.container(border=True):
            st.markdown('<div class="section-title">三态分布</div>', unsafe_allow_html=True)
            st.markdown(_chips(["%s %d" % (k, v) for k, v in chart["modalities"].items()]),
                        unsafe_allow_html=True)

    with st.expander("查看星盘文本 / 相位 / 结构化数据"):
        st.code(format_chart(chart), language=None)
        if chart.get("aspects"):
            st.dataframe(chart["aspects"], hide_index=True, use_container_width=True)
        st.json(chart)

    st.divider()
    _read_block(chart, "astro_read")


# ---------- 塔罗 ----------

def _tarot_tab():
    with st.container(border=True):
        st.markdown('<div class="section-title">抽牌</div>', unsafe_allow_html=True)
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

    cards = chart["cards"]
    cols = st.columns(min(len(cards), 3))
    for i, card in enumerate(cards):
        with cols[i % len(cols)].container(border=True):
            st.markdown(
                '<div class="section-title">%s</div>'
                '<div class="pillar"><div class="ganzhi" style="font-size:1.35rem">%s</div>'
                '<div class="meta"><em>%s</em><br>%s</div></div>'
                '<div class="note">%s</div>' % (
                    card["position"], card["name"], card["orientation"],
                    card["arcana"], card["meaning"]),
                unsafe_allow_html=True)

    with st.expander("查看牌面文本 / 结构化数据"):
        st.code(format_draw(cards), language=None)
        st.json(chart)

    st.divider()
    _read_block(chart, "tarot_read")


def main():
    st.set_page_config(
        page_title="命理古籍问答 · 排盘",
        page_icon="📜",
        layout="wide",
    )
    st.markdown(CSS, unsafe_allow_html=True)

    st.markdown(
        '<div class="hero">'
        '<h1>命理古籍知识库</h1>'
        '<div class="sub">只依据入库古籍片段作答，无据可查时<b>明确拒答</b>；'
        '排盘为历法计算，解读属文化娱乐内容，不构成任何决策建议。</div>'
        '<div class="stats">'
        '<span class="stat"><b>45</b>部古籍</span>'
        '<span class="stat"><b>8,681</b>段落</span>'
        '<span class="stat"><b>3</b>种检索策略</span>'
        '<span class="stat"><b>引用</b>逐条可核</span>'
        '</div></div>',
        unsafe_allow_html=True,
    )

    tab_qa, tab_bazi, tab_astro, tab_tarot = st.tabs(
        ["古籍问答", "八字排盘", "星盘", "塔罗"])
    with tab_qa:
        _qa_tab()
    with tab_bazi:
        _bazi_tab()
    with tab_astro:
        _astro_tab()
    with tab_tarot:
        _tarot_tab()


if __name__ == "__main__":
    main()
