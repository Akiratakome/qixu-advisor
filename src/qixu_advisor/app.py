"""顾问输入与人工选稿入口。界面重绘不调用模型。"""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from qixu_advisor.data import load_catalog, load_cases
from qixu_advisor.evaluation import (
    ROOT, DECISIONS, CandidateRating, HumanCaseRating,
    load_run_plan, save_human_rating, summarize_evaluation,
)
from qixu_advisor.generation import generate
from qixu_advisor.model import config_status
from qixu_advisor.models import GenerationRequest, SCENARIOS
from qixu_advisor.records import create_run, load_result, save_feedback


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "、".join(_text(item) for item in value)
    if isinstance(value, dict):
        if set(value) == {"address"}:
            return _text(value["address"])
        labels = {"address": "称呼", "name": "姓名", "relationship": "关系", "likes": "喜欢", "dislikes": "不喜欢"}
        return "；".join(f"{labels.get(key, key)}：{_text(item)}" for key, item in value.items() if item)
    return json.dumps(value, ensure_ascii=False)


def _records(kind: str) -> list[dict]:
    catalog = load_catalog(kind, root=ROOT)
    return catalog.get("records", []) if isinstance(catalog, dict) else catalog


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _chat_text(history: list[dict]) -> str:
    return "\n".join(f"{'顾问' if row.get('role') in {'advisor', 'assistant'} else '客户'}：{row.get('content', '')}" for row in history)


def _parse_chat(value: str) -> list[dict]:
    result = []
    for line in value.splitlines():
        line = line.strip()
        if not line:
            continue
        role = "client"
        if line.startswith(("顾问：", "顾问:")):
            role, line = "advisor", line[3:]
        elif line.startswith(("客户：", "客户:")):
            line = line[3:]
        result.append({"role": role, "content": line})
    return result


def advisor_page() -> None:
    status = config_status(ROOT)
    if not status["configured"]:
        st.warning("模型尚未配置。可以准备资料；生成前请在本地 .env 补齐：" + "、".join(status.get("missing", [])))

    scenario = st.selectbox("沟通场景", SCENARIOS)
    mode = st.radio("资料来源", ["新资料", "开发案例"], horizontal=True)
    preset = None
    if mode == "开发案例":
        choices = [c for c in load_cases("dev", root=ROOT) if c.request.scenario == scenario]
        selected = st.selectbox("选择案例", choices, format_func=lambda c: c.case_id)
        preset = selected.request
    seed = preset.client_information if preset else {}
    seed_id = selected.case_id if mode == "开发案例" else "new"
    form_key = f"input-{scenario}-{seed_id}"
    customers = _records("customers")
    customer_map = {c.get("client_id", c.get("customer_id")): c for c in customers}
    products = _records("products")
    product_map = {p["sku_id"]: p for p in products}
    events = _records("events")
    event_map = {e["event_id"]: e for e in events}
    with st.form(form_key):
        customer_ids = [None, *customer_map]
        default_client = preset.client_id if preset else None
        client_id = st.selectbox("已有客户档案（可不选）", customer_ids,
            index=customer_ids.index(default_client) if default_client in customer_ids else 0,
            format_func=lambda x: "不使用档案" if x is None else f"{customer_map[x].get('display_name', customer_map[x].get('name', x))} · {x}")
        buyer = st.text_input("联系对象", value=_text(seed.get("buyer", seed.get("name", ""))))
        recipient = _text(seed.get("recipient", ""))
        if scenario in {"产品推荐", "购后关怀", "价格异议"}:
            recipient = st.text_input("收礼人（自用时留空）", value=recipient)
        placeholders = {
            "生日与节庆": "例如：只表达生日祝福，保持简短。",
            "产品推荐": "写明这次为谁选香、喜欢与不喜欢什么、预算。",
            "购后关怀": "写明已购商品、使用感受或需要处理的问题。",
            "沉睡唤醒": "写明过去的互动、已知兴趣，以及这次联系的缘由。",
            "活动邀请": "写明客户对试香活动的兴趣，以及需要确认的问题。",
            "价格异议": "写明客户对价格、渠道或优惠的具体顾虑。",
        }
        current_need = st.text_area("本次需求", value=_text(seed.get("current_need", "")),
            placeholder=placeholders[scenario], height=100)
        preferences = _text(seed.get("long_term_preferences", ""))
        if scenario in {"产品推荐", "购后关怀", "价格异议"}:
            preferences = st.text_input("购买者长期偏好（与本次需求分开）", value=preferences)
        permissions = ["unknown", "allowed", "blocked"]
        permission_seed = seed.get("contact_permission", "unknown")
        permission_seed = {True: "allowed", False: "blocked"}.get(permission_seed, permission_seed)
        permission = st.selectbox("联系意愿", permissions,
            index=permissions.index(permission_seed) if permission_seed in permissions else 0,
            format_func=lambda x: {"unknown": "未知", "allowed": "允许联系", "blocked": "明确拒绝联系"}[x])
        occasion = None
        if scenario == "生日与节庆":
            occasion = st.text_input("祝福缘由", value=preset.occasion or "" if preset else "", placeholder="例如：客户明确告知今天生日")
        selected_products = []
        if scenario in {"产品推荐", "购后关怀", "价格异议"}:
            defaults = preset.product_ids if preset else []
            expanded = [p["sku_id"] for p in products if p["sku_id"] in defaults or p.get("product_id") in defaults]
            selected_products = st.multiselect("相关商品（未选时使用完整小目录）", list(product_map), default=expanded,
                format_func=lambda x: f"{product_map[x]['name']} {product_map[x]['volume_ml']} mL · ¥{product_map[x]['price_cny']}")
        event_id = None
        if scenario == "活动邀请":
            event_ids = [None, *event_map]
            default_event = preset.event_id if preset else None
            event_id = st.selectbox("邀请活动", event_ids,
                index=event_ids.index(default_event) if default_event in event_ids else 0,
                format_func=lambda x: "请选择具体活动" if x is None else f"{event_map[x].get('name', x)} · {event_map[x]['start_at']}")
        chat = st.text_area("对话记录（可为空，每条一行）", value=_chat_text(preset.conversation_history) if preset else "", height=120,
            placeholder="客户：这次想给妹妹挑一款。\n顾问：她平时喜欢哪一类气味？")
        submitted = st.form_submit_button("生成三条候选", type="primary")
    if submitted:
        previous_result = st.session_state.pop("active_result", None)
        def edited_value(key, value):
            # 未改动的预填字段保留结构，显示用的中文描述不反向覆盖原始资料。
            return seed[key] if key in seed and value == _text(seed[key]) else value

        client_information = {**seed, "buyer": edited_value("buyer", buyer), "recipient": edited_value("recipient", recipient),
            "current_need": edited_value("current_need", current_need),
            "long_term_preferences": edited_value("long_term_preferences", preferences), "contact_permission": permission}
        try:
            request = GenerationRequest(scenario=scenario, client_information=client_information,
                conversation_history=_parse_chat(chat), product_ids=selected_products, event_id=event_id,
                occasion=occasion, client_id=client_id)
            parent_run_id = None
            if previous_result:
                previous_input = ROOT / "artifacts/runs" / previous_result["run_id"] / "cases" / previous_result["case_id"] / "input.json"
                if previous_input.exists() and _read(previous_input).get("request") == request.model_dump(mode="json"):
                    parent_run_id = previous_result["run_id"]
            run_id = create_run(["UI-001"], root=ROOT, execution_mode="real", parent_run_id=parent_run_id)
            with st.spinner("正在生成并保存原始记录…"):
                result = generate(request, run_id, "UI-001", root=ROOT)
            st.session_state["active_result"] = result.model_dump(mode="json")
        except (ValueError, OSError) as exc:
            st.error(f"未完成：{exc}")
    active = st.session_state.get("active_result")
    if not active:
        st.caption("填写资料后生成。三条候选各自是一条完整微信消息，供顾问选择和编辑。")
        return
    st.divider()
    st.subheader("本次结果")
    st.caption(f"运行 {active['run_id']} · 案例 {active['case_id']}")
    path = ROOT / "artifacts/runs" / active["run_id"] / "cases" / active["case_id"] / "input.json"
    if path.exists():
        snapshot = _read(path)
        with st.expander("查看本次使用的事实与输入"):
            st.json({"输入": snapshot.get("request", {}), "业务资料": snapshot.get("facts", {})})
    if active["status"] != "success":
        labels = {"needs_input": "需要补充资料", "contact_blocked": "已停止：客户明确拒绝联系", "technical_failure": "生成失败"}
        st.error(labels.get(active["status"], active["status"]))
        if active.get("missing_fields"):
            st.write("待补充：" + "、".join(active["missing_fields"]))
        if active.get("error"):
            st.write(active["error"])
        return
    for warning in active.get("warnings", []):
        st.warning(warning)
    for index, candidate in enumerate(active["candidates"], start=1):
        st.markdown(f"**候选 {index}**")
        st.write(candidate["text"])
    st.caption("结构检查通过不代表内容已经通过人工评价。请核对人物、价格、规格和承诺。")
    candidates = {c["candidate_id"]: c["text"] for c in active["candidates"]}
    choice = st.radio("选择一条编辑", list(candidates),
        format_func=lambda value: f"候选 {list(candidates).index(value) + 1}", horizontal=True,
        key=f"choice-{active['run_id']}")
    with st.form(f"edit-{active['run_id']}-{choice}"):
        draft = st.text_area("编辑稿", value=candidates[choice], height=150)
        operator = st.text_input("顾问标识（可选，与客户分开记录）")
        action = st.radio("处理方式", ["保存编辑稿", "选用原稿", "弃用本组三条"], horizontal=True)
        save = st.form_submit_button("保存处理记录")
    if save:
        try:
            actions = {"保存编辑稿": "edit", "选用原稿": "select", "弃用本组三条": "discard"}
            save_feedback(active["run_id"], active["case_id"], None if action == "弃用本组三条" else choice,
                actions[action], edited_text=draft if action == "保存编辑稿" else "", operator=operator or None, root=ROOT)
            st.success("处理记录已保存；机器原稿保持原样。")
        except (ValueError, OSError) as exc:
            st.error(f"未保存：{exc}")
    st.caption("使用下方代码框的复制按钮复制当前编辑稿。保存与复制均不会发送微信。")
    st.code(draft, language=None, wrap_lines=True)


def evaluation_page() -> None:
    st.subheader("人工评价")
    st.write("先阅读机器原稿，按固定要点逐条判断。这里仅保存真人填写的评价。")
    runs = sorted((ROOT / "artifacts/runs").glob("*/manifest.json"), reverse=True)
    eligible = [p.parent.name for p in runs if _read(p).get("execution_mode") == "real"]
    if not eligible:
        st.info("尚无真实运行记录。完成真实生成后，可在这里逐条评价；当前人工评分为零。")
        return
    run_id = st.selectbox("待评价运行", eligible)
    run_dir = ROOT / "artifacts/runs" / run_id
    results = sorted((run_dir / "cases").glob("*/result.json"))
    successful = [p.parent.name for p in results if _read(p).get("status") == "success"]
    st.caption(f"该运行成功案例 {len(successful)}；其余失败或缺失会保留在汇总分母中。")
    if not successful:
        st.info("该运行暂无三条机器候选可供评价。")
        return
    case_id = st.selectbox("案例", successful)
    result = load_result(run_id, case_id, root=ROOT)
    snapshot = _read(run_dir / "cases" / case_id / "input.json")
    with st.expander("输入与事实", expanded=False):
        st.json({"输入": snapshot.get("request", {}), "业务资料": snapshot.get("facts", {})})
    plan = load_run_plan(run_id, root=ROOT)
    expectations = {row["case_id"]: row for row in plan.get("expectations", [])}
    if not expectations:
        st.info("这次单例运行未固定正式五十例评价快照。可记录本次人工判断，但不能计作正式五十例评价。")
    if case_id in expectations:
        st.write("必须回应：" + "；".join(expectations[case_id]["must_respond"]))
        st.write("不可接受：" + "；".join(expectations[case_id]["must_not"]))
    st.caption("小改只涉及称呼、语序或措辞；改人物、金额、规格、承诺或补重要顾虑均属实质改写。")
    with st.form(f"rating-{run_id}-{case_id}"):
        evaluation_id = st.text_input("评价编号", value=f"eval-{run_id}")
        rater = st.text_input("真实评价者标识")
        role = st.selectbox("评价者角色", ["开发者自评", "独立复核"])
        choices = []
        for index, candidate in enumerate(result.candidates, start=1):
            st.markdown(f"**候选 {index} · 机器原稿**")
            st.write(candidate.text)
            decision = st.selectbox("可用性", ["未评", *DECISIONS], key=f"decision-{run_id}-{case_id}-{index}")
            severe = st.selectbox("严重错误检查", ["未评", "未观察到严重错误", "存在严重错误"], key=f"severe-{run_id}-{case_id}-{index}")
            reason = st.text_input("判断理由", key=f"reason-{run_id}-{case_id}-{index}")
            edited = st.text_area("人工修改（可选，独立于机器原稿保存）", key=f"edited-{run_id}-{case_id}-{index}")
            choices.append((candidate.candidate_id, decision, severe, reason, edited))
        diversity = st.selectbox("本组三条是否包含两种不同且合理的完整选择", ["未评", "是", "否"])
        diversity_reason = st.text_input("组内差异的判断理由")
        confirmed = st.checkbox("我是实际评价者；以上是我阅读原稿后的判断")
        save = st.form_submit_button("保存本例人工评价", type="primary")
    if save:
        if not confirmed or diversity == "未评" or any(d == "未评" or s == "未评" for _, d, s, _, _ in choices):
            st.error("请完成三条候选、组内差异的评价，并确认由真人填写。")
            return
        try:
            rating = HumanCaseRating(run_id=run_id, case_id=case_id, rater=rater, rater_role=role,
                human_confirmed=True,
                candidates=[CandidateRating(candidate_id=c, decision=d, serious_error=s == "存在严重错误", reason=r, edited_text=e) for c, d, s, r, e in choices],
                two_distinct_usable=diversity == "是", diversity_reason=diversity_reason)
            save_human_rating(evaluation_id, rating, root=ROOT)
            summary = summarize_evaluation(evaluation_id, run_id, rater, root=ROOT)
            st.success("评价已追加保存。未评价的案例继续保留在分母中。")
            st.json(summary)
        except (ValueError, OSError) as exc:
            st.error(f"未保存：{exc}")


def main() -> None:
    st.set_page_config(page_title="栖序 QIXU · 顾问助手", layout="centered")
    st.title("栖序 QIXU")
    st.caption("香水顾问写作助手 · 品牌、客户与业务资料均为虚构")
    page = st.radio("工作区", ["顾问写作", "人工评价"], horizontal=True)
    if page == "顾问写作":
        advisor_page()
    else:
        evaluation_page()


if __name__ == "__main__":
    main()
