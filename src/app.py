import sys
from datetime import date, time
from pathlib import Path

import streamlit as st

# 无论从仓库根目录还是 src/ 内部启动，都能找到同级模块
sys.path.append(str(Path(__file__).resolve().parent))

from fortune.astro import format_chart, natal_chart
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


def _show_reading(chart, question, note, key):
    """排完盘后点「生成解读」才调模型——排盘本身不花钱。"""
    if not has_api_key():
        st.info("没有配置 DEEPSEEK_API_KEY，暂时只能看盘面，不能生成解读。")
        return
    if st.button("生成解读", type="primary", key=key):
        with st.spinner("正在解读盘面…"):
            try:
                res = read(chart, question=question, user_note=note)
            except Exception as exc:
                st.error("解读失败：%s" % exc)
                return
        if res["summary"]:
            st.success(res["summary"])
        for sec in res["sections"]:
            st.subheader(sec["title"])
            st.markdown(sec["content"])
        st.caption(res["disclaimer"])


def _bazi_tab():
    st.markdown("八字按**出生地当地时间**排，节气与干支由历法库计算，同一份输入永远得到同一个盘。")
    with st.form("bazi_form"):
        col1, col2, col3 = st.columns(3)
        d = col1.date_input("出生日期", value=date(2000, 1, 1), min_value=date(1900, 1, 1), key="bazi_d")
        t = col2.time_input("出生时间（不确定就填 12:00）", value=time(12, 0), key="bazi_t")
        gender = col3.selectbox("性别", ["male", "female"], key="bazi_g")
        question = st.text_input("想问什么（可留空）", key="bazi_q")
        submitted = st.form_submit_button("排盘", type="primary")

    if submitted:
        try:
            st.session_state["bazi_chart"] = paipan(
                d.year, d.month, d.day, t.hour, t.minute, gender
            )
        except ValueError as exc:
            st.error(str(exc))
            st.session_state.pop("bazi_chart", None)

    chart = st.session_state.get("bazi_chart")
    if chart:
        st.code(format_bazi(chart), language=None)
        with st.expander("查看结构化数据"):
            st.json(chart)
        _show_reading(chart, st.session_state.get("bazi_q"), None, "bazi_read")


def _astro_tab():
    st.markdown("星盘用**地心视黄经**计算，宫位为**整宫制**。出生时间越准，上升和宫位越准（差 2 小时上升会偏一个星座）。")
    with st.form("astro_form"):
        col1, col2, col3 = st.columns(3)
        d = col1.date_input("出生日期", value=date(2000, 1, 1), min_value=date(1900, 1, 1), key="as_d")
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
        question = st.text_input("想问什么（可留空）", key="as_q")
        submitted = st.form_submit_button("排盘", type="primary")

    if submitted:
        try:
            st.session_state["astro_chart"] = natal_chart(
                d.year, d.month, d.day, t.hour, t.minute, tz, lat, lon, city
            )
        except ValueError as exc:
            st.error(str(exc))
            st.session_state.pop("astro_chart", None)

    chart = st.session_state.get("astro_chart")
    if chart:
        st.code(format_chart(chart), language=None)
        with st.expander("查看结构化数据"):
            st.json(chart)
        _show_reading(chart, st.session_state.get("as_q"), None, "astro_read")


def _tarot_tab():
    st.markdown("抽到什么是随机的；**同一组牌怎么解释**才是塔罗真正在做的部分，所以别反复抽到满意为止。")
    with st.form("tarot_form"):
        col1, col2 = st.columns(2)
        spread = col1.selectbox("牌阵", list(SPREADS), format_func=lambda k: SPREADS[k][0], key="tt_s")
        seed_text = col2.text_input("固定种子（可留空，填了结果可复现）", key="tt_seed")
        question = st.text_input("想问什么", key="tt_q")
        submitted = st.form_submit_button("抽牌", type="primary")

    if submitted:
        seed = None
        if seed_text.strip():
            try:
                seed = int(seed_text.strip())
            except ValueError:
                st.warning("种子要是整数，这次按随机处理")
        st.session_state["tarot_chart"] = draw_tarot(seed=seed, spread=spread)

    chart = st.session_state.get("tarot_chart")
    if chart:
        st.code(format_draw(chart["cards"]), language=None)
        _show_reading(chart, st.session_state.get("tt_q"), None, "tarot_read")


def _qa_tab():
    with st.sidebar:
        st.header("检索配置")
        mode = st.radio("检索策略", ["rrf", "bm25", "dense"], index=0)
        top_k = st.slider("召回Top-k", min_value=1, max_value=10, value=5)
        st.divider()
        st.info("模型 DeepSeek Chat | 强制JSON输出+引用校验")

    question = st.text_input("请输入你的问题")
    run_bnt = st.button("开始回答", type="primary")

    if run_bnt and not question.strip():
        st.warning("请输入问题")
    elif run_bnt:
        with st.spinner("检索古籍+大模型生成回答中，请稍后~"):
            res = answer(question, top_k=top_k, mode=mode)
        st.success("推理完成")
        st.divider()
        col1, col2 = st.columns([0.6, 0.4])
        with col1:
            st.subheader("模型回答")
            if res["can_answer"] is False:
                st.warning(res["answer"])
            elif res["can_answer"] is None:
                st.error("模型输出异常JSON解析失败")
                st.code(res.get("raw", ""), language="json")
            else:
                st.markdown(res["answer"])
                if len(res["invalid_citations"]) > 0:
                    st.error(f"发现非法引用：{res['invalid_citations']}")
        with col2:
            st.subheader("本次召回chunk_id")
            st.write(res["retrieved_chunk_ids"])
            st.subheader("模型有效引用chunk_id")
            st.write(res["citations_chunk_ids"])
        st.divider()
        with st.expander("查看原始返回JSON(调试用)"):
            st.json(res)


def main():
    st.set_page_config(
        page_title="命理古籍问答 · 排盘",
        page_icon="📜",
        layout="wide",
    )
    st.title("命理古籍知识库问答")
    st.markdown(
        ">知识库包含《张果星宗》《兰台妙选》等星命古籍，仅基于入库古籍片段作答，无资料时自动拒答。"
        "排盘为历法计算，解读为文化娱乐内容，不构成任何决策建议。"
    )

    tab_qa, tab_bazi, tab_astro, tab_tarot = st.tabs(["古籍问答", "八字排盘", "星盘", "塔罗"])
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
