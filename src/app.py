import streamlit as st
import sys
import json
sys.path.append("./src")
from rag import answer
st.set_page_config(
    page_title="古籍命理问答",
    page_icon="📜",
    layout="wide"
)
st.title("命理古籍知识库问答")
st.markdown(">知识库包含《张果星宗》《兰台妙选》等星命古籍，仅基于入库古籍片段作答，无资料时自动拒答")
with st.sidebar:
    st.header("检索配置")
    mode=st.radio("检索策略",["rrf","bm25","dense"],index=0)
    top_k=st.slider("召回Top-k",min_value=1,max_value=10,value=5)
    st.divider()
    st.info("模型 Deepsee Chat | 强制JSON输出+引用校验")

question=st.text_input("请输入你的问题")
run_bnt=st.button("开始回答",type="primary")
if run_bnt:
    with st.spinner("检索古籍+大模型生成回答中，请稍后~"):
        res=answer(question,top_k=top_k,mode=mode)
    st.success("推理完成")
    st.divider()
    col1,col2=st.columns([0.6,0.4])
    with col1:
        st.subheader("模型回答")
        if res["can_answer"] is False:
            st.warnning(res["answer"])
        elif res["can_answer"] is None:
            st.error("模型输出异常JSON解析失败")
            st.code(res.get("raw",""),language="json")
        else:
            st.markdown(res["answer"])
            if len(res["invalid_citations"])>0:
                st.error(f"发现非法引用：{res['invalid_citations']}")
        with col2:
            st.subheader("本次召回chunk_id")
            retrieved_ids=json.loads(res["retrieved_chunk_ids"])
            st.write(retrieved_ids)
            st.subheader("模型有效引用chunk_id")
            cited_ids=json.loads(res["citations_chunk_ids"])
            st.write(cited_ids) 
        st.divider()
        with st.expander("查看原始返回JSON(调试用)"):
            st.json(res)
elif run_bnt and not question.strip():
    st.warning("请输入问题")
    