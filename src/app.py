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
import time as _time
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
import datahub
import evalhub

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

CSS = "<style>" + (Path(__file__).with_name("app_theme.css")).read_text(encoding="utf-8") + "</style>"


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

MODES = ("单 Agent", "多 Agent", "单轮 RAG")


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


def _render_turn(msg, question=""):
    """渲染一轮对话。引用、轨迹、耗时都挂在对应的助手消息下面，不串到下一轮。"""
    res = msg.get("meta") or {}
    with st.chat_message(msg["role"]):
        if msg.get("error"):
            st.error(msg["content"])
            return

        content = msg.get("content") or ""
        if content:
            st.markdown(content)
        if msg.get("role") == "assistant" and res.get("can_answer") is None:
            st.error("没有拿到可用回答（JSON 解析失败或缺少有效引用）")
            if res.get("raw"):
                st.code(res["raw"], language="json")

        if not res:
            return

        bits = [msg.get("mode") or ""]
        if res.get("steps") is not None:
            bits.append("步数 %s" % res.get("steps"))
        if res.get("llm_calls") is not None:
            bits.append("LLM 调用 %s" % res.get("llm_calls"))
        if msg.get("elapsed") is not None:
            bits.append("%.1fs" % msg["elapsed"])
        st.caption(" · ".join(b for b in bits if b))

        standalone = res.get("rewritten_question")
        if standalone and question and standalone != question:
            st.caption("追问改写为：%s" % standalone)
        if res.get("refusal_reason"):
            st.caption("拒答理由：%s" % res["refusal_reason"])
        if res.get("citations_chunk_ids"):
            st.markdown(_chips(res["citations_chunk_ids"], seal=True), unsafe_allow_html=True)
        elif res.get("can_answer") is False:
            st.caption("本次无有效引用")
        if res.get("invalid_citations"):
            st.error("发现非法引用：%s" % res["invalid_citations"])
        if res.get("invalid_output"):
            st.warning("输出被标记为不合规：声称能答，但存在无效引用。")

        trace = res.get("trace") or []
        if trace or res.get("plan") or res.get("verdict"):
            with st.expander("执行轨迹（%d 步）" % len(trace), expanded=False):
                if res.get("plan"):
                    st.markdown('<div class="section-title">Planner 计划</div>',
                                unsafe_allow_html=True)
                    st.json(res["plan"])
                for t in trace:
                    st.markdown("**Step %s · %s**" % (t.get("step", "?"),
                                                      t.get("action") or "?"))
                    if t.get("thought"):
                        st.caption(t["thought"])
                    if t.get("chunk_ids"):
                        st.caption("chunk：" + "、".join(str(x) for x in t["chunk_ids"]))
                    if t.get("ok") is False:
                        st.error(t.get("error") or "工具调用失败")
                if res.get("verdict"):
                    st.markdown('<div class="section-title">Verifier 判定</div>',
                                unsafe_allow_html=True)
                    st.json(res["verdict"])


def _qa_tab():
    messages = st.session_state.setdefault("qa_messages", [])

    head_l, head_r = st.columns([0.62, 0.38], gap="large")
    with head_l:
        st.markdown('<div class="prompt-label">问一个古籍里的问题</div>',
                    unsafe_allow_html=True)
        st.caption("可以连续追问。历史只用于理解指代，引用仍然只来自本轮实际检索到的片段。")
        mode_label = st.radio(
            "回答模式", MODES, index=0, horizontal=True, key="qa_mode",
            help="单 Agent：ReAct 工具调用（默认）；多 Agent：Supervisor/Retriever/Verifier；"
                 "单轮 RAG：固定一次检索的基线",
        )
        if mode_label == "单轮 RAG":
            c1, c2 = st.columns([0.55, 0.45])
            mode = c1.radio("检索策略", ["rrf", "bm25", "dense"], index=0,
                            horizontal=True, key="qa_retrieval",
                            help="rrf=语义+字面融合，bm25=精确术语，dense=语义")
            top_k = c2.slider("召回条数", min_value=1, max_value=10, value=5, key="qa_topk")
        else:
            mode, top_k = "rrf", 5
            st.caption("Agent 会自己决定检索策略与条数")

        # 公网 Demo 不一定配了服务端 key，让访客能自带一个；只存在本次会话
        if has_api_key():
            api_key = None
            _quota_caption()
        else:
            st.markdown('<div class="note">公网未配置服务端 Key，可填自己的 DeepSeek Key'
                        '（仅本次会话，不落盘）。</div>', unsafe_allow_html=True)
            api_key = st.text_input("DeepSeek API Key", type="password", key="qa_key") or None

    with head_r:
        if messages:
            if st.button("新对话", use_container_width=True, key="qa_new"):
                st.session_state["qa_messages"] = []
                st.session_state["qa_input"] = ""
                st.rerun()
            st.markdown(
                '<div class="note">当前对话共 %d 条消息。追问会先改写成独立问题，'
                '历史不会作为回答证据。</div>' % len(messages),
                unsafe_allow_html=True,
            )
        else:
            st.markdown('<div class="section-title">可以这样问</div>', unsafe_allow_html=True)
            for i, ex in enumerate(EXAMPLES):
                if st.button(ex, key="ex%d" % i, use_container_width=True):
                    st.session_state["qa_input"] = ex
                    st.rerun()

    if not messages:
        st.markdown(
            '<div class="how">'
            '<div><h3>检索</h3><p>BGE-M3 语义召回与 BM25 字面召回各取 40 条，'
            'RRF 融合后保留前 5 段；每条引用都能定位到具体 chunk。</p></div>'
            '<div><h3>编排</h3><p>单 Agent 用 ReAct 调 7 个工具；多 Agent 由 Supervisor 拆题、'
            'Retriever 补证、Verifier 复核，再交给 Synthesizer 落笔。</p></div>'
            '<div><h3>校验</h3><p>引用白名单只保留真正看过的片段；没有有效引用就拒答，'
            '不拿主题相近的段落硬凑。</p></div>'
            '</div>',
            unsafe_allow_html=True,
        )
        st.divider()

    if messages:
        st.markdown('<div class="section-title" style="margin-top:.6rem">对话</div>',
                    unsafe_allow_html=True)
        prev_q = ""
        for msg in messages[-12:]:
            _render_turn(msg, prev_q)
            if msg.get("role") == "user":
                prev_q = msg.get("content") or ""
        st.divider()

    with st.form("qa_form", clear_on_submit=True):
        c1, c2 = st.columns([0.82, 0.18])
        question = c1.text_input(
            "你的问题", key="qa_input", label_visibility="collapsed",
            placeholder="继续追问，例如：那《渊海子平》里怎么说？",
        )
        submitted = c2.form_submit_button("发送", type="primary", use_container_width=True)

    if not submitted:
        return
    question = (question or "").strip()
    if not question:
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

    history = _as_history(messages)
    messages.append({"role": "user", "content": question})

    spinner = ("检索古籍 + 生成回答中；首次使用要先加载检索模型，可能需要一两分钟…"
               if mode_label == "单轮 RAG"
               else "Agent 规划 / 检索 / 校验中；首次使用要先加载检索模型…")
    started = _time.perf_counter()
    try:
        with st.spinner(spinner):
            if mode_label == "单 Agent":
                from agent import agent_answer as _agent_answer
                res = _agent_answer(question, api_key=api_key, history=history)
            elif mode_label == "多 Agent":
                from agent_multi import agent_answer as _agent_answer
                res = _agent_answer(question, api_key=api_key, history=history)
            else:
                res = answer(question, top_k=top_k, mode=mode, api_key=api_key, history=history)
        elapsed = _time.perf_counter() - started
        messages.append({
            "role": "assistant",
            "content": res.get("answer") or "",
            "meta": res,
            "elapsed": elapsed,
            "mode": mode_label,
        })
    except Exception as exc:
        messages.append({
            "role": "assistant",
            "content": "生成失败：{}".format(exc),
            "error": True,
        })
    st.rerun()

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
    st.markdown('<div class="prompt-label">数据中台</div>', unsafe_allow_html=True)
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
            '<div class="section-title">当前版本 · %s</div>'
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
    st.markdown('<div class="section-title" style="margin-top:1rem">质量门 · %d 通过 / %d 警告 / %d 失败</div>'
                % (len(checks) - bad - warn, warn, bad), unsafe_allow_html=True)
    st.dataframe(
        [{"检查": c["check_name"], "结果": _status_cn(c["status"]),
          "值": c["value"], "说明": c["detail"]} for c in checks],
        hide_index=True, use_container_width=True,
    )

    st.markdown('<div class="section-title" style="margin-top:1rem">资产与哈希</div>',
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
    st.markdown('<div class="prompt-label">评测中台</div>', unsafe_allow_html=True)
    st.caption("把每次评测登记成带配置、数据集版本和逐题明细的 run；"
               "两次 run 可以直接比，掉点超过阈值判回归失败。")

    runs = evalhub.list_runs(limit=200)
    by_suite = {}
    for r in runs:
        by_suite.setdefault(r["suite"], r)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("登记 run", len(runs))
    # 检索看项目声明的当前基线（8681 段那版），不是「最后导入的文件」——
    # 导入顺序取决于文件 mtime，拿它当「最新」会误导。
    ret = next((r for r in runs if r["source"] == "results_8681_tuned.csv#rrf"),
               by_suite.get("retrieval"))
    c2.metric("检索 R@5（当前基线）", "—" if not ret or ret["metrics"].get("line_recall") is None
              else "%.1f%%" % (ret["metrics"]["line_recall"] * 100))
    # Agent 看多 Agent 组的均值；单次 run 会受模型波动影响，不能拿来当门面。
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

    st.markdown('<div class="section-title" style="margin-top:1rem">Run 账本</div>',
                unsafe_allow_html=True)
    st.dataframe(
        [{"编号": r["id"], "登记时间": r["created_at"], "套件": _suite_cn(r["suite"]),
          "后端": r["backend"], "数据集": _version_text(r["dataset_version"]),
          "关键指标": _run_metric_text(r), "名称": r["name"]} for r in runs],
        hide_index=True, use_container_width=True,
    )

    st.markdown('<div class="section-title" style="margin-top:1rem">逐题明细</div>',
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

    st.markdown('<div class="section-title" style="margin-top:1rem">版本对比 / 回归门</div>',
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

def main():
    st.set_page_config(
        page_title="命理古籍 RAG Agent",
        page_icon="📜",
        layout="wide",
    )
    st.markdown(CSS, unsafe_allow_html=True)

    st.markdown(
        '<div class="hero">'
        '<div>'
        '<h1>命理古籍<br>RAG Agent</h1>'
        '<p class="sub">45 部古籍、8,681 个段落。先检索、再作答，'
        '每个结论都能回到原文；证据不足时<b>明确拒答</b>。</p>'
        '<div class="stats">'
        '<span class="stat"><b>45</b>部古籍</span>'
        '<span class="stat"><b>8,681</b>段落</span>'
        '<span class="stat"><b>340 万</b>字语料</span>'
        '<span class="stat"><b>7</b>个工具</span>'
        '</div>'
        '</div>'
        '<aside class="hero-aside">'
        '<div class="aside-label">当前评测（样本有限）</div>'
        '<div class="metric-row"><span>检索 Recall@5</span><b>75.0%</b></div>'
        '<div class="metric-row"><span>单 Agent</span><b>8.0 / 15</b></div>'
        '<div class="metric-row"><span>多 Agent</span><b>12.7 / 15</b></div>'
        '<div class="metric-row"><span>拒答正确</span><b>9 / 9</b></div>'
        '<div class="aside-note">30 题检索集 / 15 题 Agent 集，三次运行均值；不宣称统计显著。</div>'
        '</aside>'
        '</div>',
        unsafe_allow_html=True,
    )

    tab_qa, tab_eval, tab_data, tab_bazi, tab_astro, tab_tarot = st.tabs(
        ["古籍问答", "评测中台", "数据中台", "八字排盘", "星盘", "塔罗"])
    with tab_qa:
        _qa_tab()
    with tab_eval:
        _eval_tab()
    with tab_data:
        _data_tab()
    with tab_bazi:
        _bazi_tab()
    with tab_astro:
        _astro_tab()
    with tab_tarot:
        _tarot_tab()


if __name__ == "__main__":
    main()
