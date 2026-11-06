"""临时浏览器验证页面：复用真实应用编辑逻辑，加载已有真实结果。"""

import streamlit as st

from qixu_advisor import app
from qixu_advisor.records import load_result

RUN_ID = "run-20261106T080044-fcfb87ee"
st.set_page_config(page_title="栖序 · 既有真实结果复核", layout="centered")
st.warning("验证界面：加载既有真实运行，仅检查编辑保存。由 Codex 操作，不是真人评价。")
st.caption(f"已保存的真实运行：{RUN_ID} · 本页不执行模型调用")


def no_new_generation(*args, **kwargs):
    raise ValueError("验证界面不允许新生成；只复核已保存的真实结果。")


app.generate = no_new_generation
if "active_result" not in st.session_state:
    st.session_state["active_result"] = load_result(RUN_ID, "UI-001").model_dump(mode="json")
app.advisor_page()
