"""顾问工作台。界面重绘不调用模型：只有点击「分析并提问」与「生成三条候选」才调用。"""

from __future__ import annotations

import html as html_lib
import json
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from qixu_advisor import generation as generation_module
from qixu_advisor.data import load_catalog, load_cases
from qixu_advisor.evaluation import (
    ROOT, DECISIONS, CandidateRating, HumanCaseRating,
    load_run_plan, save_human_rating, summarize_evaluation,
)
from qixu_advisor.generation import generate
from qixu_advisor.model import config_status
from qixu_advisor.models import SCENARIOS, GenerationRequest
from qixu_advisor.records import create_run, load_result, save_feedback


_CHAT_KEY = "qixu_chat_text"
_CLIENT_KEY = "qixu_client"
_SCENARIO_KEY = "qixu_scenario"
_EVENT_KEY = "qixu_event"
_ANALYSIS_KEY = "qixu_analysis"
_LANG_KEY = "qixu_set_language"
_TONE_KEY = "qixu_set_tone"
_LENGTH_KEY = "qixu_set_length"
_GOAL_KEY = "qixu_set_goal"
_SHOW_DEV_KEY = "qixu_show_dev_cases"
_DEV_CASE_KEY = "qixu_dev_case"
_DEV_PENDING_KEY = "qixu_dev_pending"

_LANGUAGE_OPTIONS = {"中文": "zh-CN", "English": "en"}
_TONE_OPTIONS = {"自然": "natural", "温和": "warm", "直接": "direct"}
_LENGTH_OPTIONS = {"简短": "short", "标准": "standard"}
_GOAL_OPTIONS = {"按场景默认": None, "回答问题": "answer", "帮助选择": "recommend", "提出下一步": "next_step"}
# 设置控件以中文标签存储于 session_state，生成时映射回 GenerationRequest 的取值。
_LANGUAGE_LABELS = {"zh-CN": "中文", "en": "English"}
_TONE_LABELS = {"natural": "自然", "warm": "温和", "direct": "直接"}
_LENGTH_LABELS = {"short": "简短", "standard": "标准"}
_GOAL_LABELS = {None: "按场景默认", "answer": "回答问题", "recommend": "帮助选择", "next_step": "提出下一步"}

_CSS = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@500;600;700&display=swap" rel="stylesheet">
<style>
html, body, [data-testid="stAppViewContainer"] {
  color: #1F1B16;
  background: #FAF7F2;
}
[data-testid="stHeader"] {
  background: transparent;
}
h1, h2, h3, h4 {
  font-family: "Noto Serif SC", "Songti SC", "STSong", serif !important;
  color: #1F1B16;
  letter-spacing: 0.04em;
}
p, li, span, [data-testid="stMarkdownContainer"] {
  font-family: system-ui, -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
}
[data-testid="stSidebar"] {
  background: #F3EDE2;
}
.qixu-brand {
  padding: 6px 0 16px 0;
  margin: 0 0 14px 0;
  border-bottom: 1px solid #E4D9C6;
}
.qixu-brand-title {
  font-family: "Noto Serif SC", serif;
  font-size: 2.05rem;
  font-weight: 700;
  letter-spacing: 0.16em;
  color: #1F1B16;
}
.qixu-brand-sub {
  margin-top: 6px;
  font-size: 0.95rem;
  letter-spacing: 0.10em;
  color: #B08D57;
}
.qixu-card-head {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin: 2px 0 10px 0;
}
.qixu-card-no {
  font-family: "Noto Serif SC", serif;
  font-size: 1.02rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  color: #B08D57;
}
.qixu-card-meta {
  font-size: 0.78rem;
  letter-spacing: 0.05em;
  color: #8A7C66;
}
.qixu-card-body {
  font-size: 1rem;
  line-height: 1.95;
  color: #1F1B16;
  white-space: pre-wrap;
  margin-bottom: 4px;
}
.qixu-card-divider {
  border-top: 1px solid #E4D9C6;
  margin: 10px 0 6px 0;
}
.stButton > button {
  border-radius: 8px;
  letter-spacing: 0.06em;
}
.stButton > button[kind="primary"] {
  background: #B08D57;
  border-color: #B08D57;
  color: #FFFFFF;
}
.stButton > button[kind="primary"]:hover {
  background: #9A7748;
  border-color: #9A7748;
  color: #FFFFFF;
}
.stButton > button[kind="secondary"] {
  border: 1px solid #B08D57;
  color: #B08D57;
  background: transparent;
}
[data-testid="stExpander"] details {
  border: 1px solid #E4D9C6;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.55);
}
[data-testid="stDivider"] {
  border-color: #E4D9C6;
}
</style>
"""

# components.html 不支持 key；各卡片以唯一 DOM id 与独立嵌入正文区分，互不影响。
_COPY_HTML_TEMPLATE = """
<div style="font-family: system-ui, -apple-system, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;">
  <button id="__ID__-btn" title="复制当前正文（含未保存修改）" onclick="__qixuCopy('__ID__')"
          style="appearance:none; border:1px solid #B08D57; background:#B08D57; color:#FFFFFF;
                 border-radius:8px; padding:8px 28px; font-size:15px; letter-spacing:0.10em; cursor:pointer;">复制</button>
  <span id="__ID__-status" style="margin-left:14px; color:#B08D57; font-size:14px;"></span>
  <textarea id="__ID__-manual" style="display:none; width:100%; height:110px; margin-top:10px;">__TEXT__</textarea>
  <script>
    window.__qixuText = window.__qixuText || {};
    window.__qixuText['__ID__'] = __PAYLOAD__;
    function __qixuCopy(id) {
      var status = document.getElementById(id + '-status');
      var manual = document.getElementById(id + '-manual');
      var finish = function (ok) {
        if (ok) {
          status.textContent = '已复制';
        } else {
          manual.style.display = 'block';
          status.textContent = '自动复制失败，请手动复制下方文本';
        }
      };
      var legacy = function () {
        manual.style.display = 'block';
        manual.focus();
        manual.select();
        try {
          finish(document.execCommand('copy'));
        } catch (error) {
          finish(false);
        }
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(window.__qixuText[id]).then(function () { finish(true); }, function () { legacy(); });
      } else {
        legacy();
      }
    }
  </script>
</div>
"""


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


def _copy_button(text: str, unique_id: str) -> None:
    escaped = html_lib.escape(text)
    payload = json.dumps(text, ensure_ascii=False)
    document = (_COPY_HTML_TEMPLATE.replace("__ID__", unique_id)
                .replace("__TEXT__", escaped).replace("__PAYLOAD__", payload))
    components.html(document, height=56, scrolling=True)


def _analysis_fields(result):
    """兼容核心返回的 AnalysisResult 模型或 dict；场景必须是六场景中文原词。"""
    if isinstance(result, dict):
        scenario = result.get("scenario")
        current_need = result.get("current_need") or ""
        missing = result.get("missing_questions") or []
    else:
        scenario = getattr(result, "scenario", None)
        current_need = getattr(result, "current_need", "") or ""
        missing = list(getattr(result, "missing_questions", []) or [])
    if scenario not in SCENARIOS:
        raise ValueError(f"识别场景无效：{scenario!r}；须为六场景中文原词之一")
    if not isinstance(missing, list):
        missing = [missing]
    return scenario, str(current_need), [str(item) for item in missing]


def _run_analysis(history: list[dict], client_information: dict):
    analyzer = getattr(generation_module, "analyze_conversation", None)
    if analyzer is None:
        raise RuntimeError("分析能力尚未接入（generation.analyze_conversation 缺失）")
    return analyzer(history, client_information, root=ROOT)


def _index_of(options: list, key: str, default) -> int:
    current = st.session_state.get(key, default)
    return options.index(current) if current in options else options.index(default)


def _brand_header() -> None:
    st.markdown(
        '<div class="qixu-brand"><div class="qixu-brand-title">栖序 QIXU</div>'
        '<div class="qixu-brand-sub">香水顾问写作助手 · 资料均为虚构</div></div>',
        unsafe_allow_html=True,
    )


def _writing_settings() -> None:
    st.sidebar.markdown("### 写作设置")
    st.sidebar.selectbox("输出语言", list(_LANGUAGE_OPTIONS), index=_index_of(list(_LANGUAGE_OPTIONS), _LANG_KEY, "中文"), key=_LANG_KEY,
        help="生成时传入 GenerationRequest；仅影响本次生成。")
    st.sidebar.selectbox("语气", list(_TONE_OPTIONS), index=_index_of(list(_TONE_OPTIONS), _TONE_KEY, "自然"), key=_TONE_KEY)
    st.sidebar.selectbox("篇幅", list(_LENGTH_OPTIONS), index=_index_of(list(_LENGTH_OPTIONS), _LENGTH_KEY, "标准"), key=_LENGTH_KEY)
    st.sidebar.selectbox("本次目标", list(_GOAL_OPTIONS), index=_index_of(list(_GOAL_OPTIONS), _GOAL_KEY, "按场景默认"), key=_GOAL_KEY,
        help="「按场景默认」表示生成时由场景解析默认目标。")


def _model_status() -> None:
    st.sidebar.markdown("### 模型与资料状态")
    status = config_status(ROOT)
    if status["configured"]:
        st.sidebar.caption(f"模型已配置：{status.get('model')} · {status.get('base_url')}")
    else:
        st.sidebar.warning("模型尚未配置：" + "、".join(status.get("missing", [])) + "。请在本地 .env 补齐；此处不输入密钥。")
    parts = []
    for kind, label in (("customers", "客户档案"), ("products", "商品 SKU"), ("events", "活动")):
        try:
            parts.append(f"{label} {len(_records(kind))}")
        except (OSError, ValueError):
            parts.append(f"{label} 读取失败")
    st.sidebar.caption("资料均为虚构 · " + " · ".join(parts))


def _queue_dev_case() -> None:
    """按钮 on_click 回调：把预设写入待应用队列并重跑；重跑开始时所有控件尚未实例化，可安全写入。"""
    selected = st.session_state.get(_DEV_CASE_KEY)
    if selected is None:
        return
    preset = selected.request
    customers = {c.get("client_id", c.get("customer_id")): c for c in _records("customers")}
    st.session_state[_DEV_PENDING_KEY] = {
        _CHAT_KEY: _chat_text(preset.conversation_history),
        _CLIENT_KEY: preset.client_id if preset.client_id in customers else None,
        _LANG_KEY: _LANGUAGE_LABELS.get(preset.output_language, "中文"),
        _TONE_KEY: _TONE_LABELS.get(preset.tone, "自然"),
        _LENGTH_KEY: _LENGTH_LABELS.get(preset.length, "标准"),
        _GOAL_KEY: _GOAL_LABELS.get(preset.goal, "按场景默认"),
    }
    st.rerun()


def _apply_dev_pending() -> None:
    pending = st.session_state.pop(_DEV_PENDING_KEY, None)
    if not pending:
        return
    for key, value in pending.items():
        st.session_state[key] = value


def _dev_cases() -> None:
    st.sidebar.markdown("### 开发案例（内部）")
    if not st.sidebar.checkbox("显示开发案例（内部）", key=_SHOW_DEV_KEY):
        return
    st.sidebar.caption("内部使用：仅用于离线调试与复现，默认不对用户展示。")
    choices = load_cases("dev", root=ROOT)
    st.sidebar.selectbox("选择案例", choices, format_func=lambda c: c.case_id, key=_DEV_CASE_KEY)
    st.sidebar.button("载入到主区", on_click=_queue_dev_case)


def advisor_page() -> None:
    customers = _records("customers")
    customer_map = {c.get("client_id", c.get("customer_id")): c for c in customers}
    customer_ids = [None, *customer_map]
    default_client = st.session_state.get(_CLIENT_KEY)
    client_id = st.selectbox("客户档案（可不选）", customer_ids,
        index=customer_ids.index(default_client) if default_client in customer_ids else 0,
        format_func=lambda x: "不使用档案" if x is None else f"{customer_map[x].get('display_name', customer_map[x].get('name', x))} · {x}",
        key=_CLIENT_KEY)
    chat = st.text_area("对话记录（每行一条）", key=_CHAT_KEY, height=150,
        placeholder="客户：这次想给妹妹挑一款。\n顾问：她平时喜欢哪一类气味？\n客户：她喜欢清爽一点的味道。",
        help="每行一条消息，以「客户：」或「顾问：」开头；生成与分析都会重新解析这里的原文。")

    if st.button("分析并提问", type="primary"):
        history = _parse_chat(chat)
        profile = customer_map.get(client_id) if client_id else None
        client_information = dict(profile) if profile else {}
        if not history and not client_information:
            st.error("请先粘贴对话记录或选择客户档案，再开始分析。")
        else:
            with st.spinner("正在理解对话并整理待确认问题…"):
                try:
                    scenario, current_need, missing = _analysis_fields(_run_analysis(history, client_information))
                except Exception as exc:  # noqa: BLE001 界面把失败原因原样显示，不自动重试
                    st.error(f"分析未完成：{exc}")
                else:
                    st.session_state[_ANALYSIS_KEY] = {
                        "scenario": scenario,
                        "current_need": current_need,
                        "missing_questions": missing,
                        "conversation_text": chat,
                    }
                    st.session_state.pop(_SCENARIO_KEY, None)
                    st.success("分析完成。可调整场景；把客户答复以「客户：…」补进对话后再生成。")

    analysis = st.session_state.get(_ANALYSIS_KEY)
    if not analysis:
        st.caption("工作流：粘贴对话（或选择客户档案）→ 分析并提问 → 核对场景与需求 → 生成三条候选。需求由 AI 从对话分析，不手工填写。")
        return

    st.divider()
    scenario = st.selectbox("识别场景（可调整）", list(SCENARIOS),
        index=SCENARIOS.index(analysis["scenario"]) if analysis["scenario"] in SCENARIOS else 0,
        key=_SCENARIO_KEY, help="默认取 AI 识别结果；顾问可据实际情况调整，调整后按新场景生成。")
    st.markdown("**本次需求摘要**")
    st.info(analysis["current_need"] or "（分析未给出摘要）")
    if analysis["missing_questions"]:
        st.markdown("**待确认问题**")
        for question in analysis["missing_questions"]:
            st.markdown(f"- {html_lib.escape(question)}")
    else:
        st.caption("本轮资料足够，暂无必须确认的问题。")
    if chat != analysis["conversation_text"]:
        st.info("对话内容较分析时已有更新；如需按最新对话重新识别，请再次点击「分析并提问」。")

    event_id = None
    if scenario == "活动邀请":
        events = _records("events")
        event_map = {e["event_id"]: e for e in events}
        event_ids = [None, *event_map]
        event_id = st.selectbox("邀请活动", event_ids, index=0, key=_EVENT_KEY,
            format_func=lambda x: "请选择具体活动" if x is None else f"{event_map[x].get('name', x)} · {event_map[x]['start_at']}")

    if st.button("生成三条候选", type="primary"):
        profile = customer_map.get(client_id) if client_id else None
        client_information = dict(profile) if profile else {}
        client_information["current_need"] = analysis["current_need"]
        client_information.setdefault("contact_permission", "unknown")
        occasion = None
        if scenario == "生日与节庆":
            occasion = analysis["current_need"]
            client_information["occasion"] = occasion
        request = GenerationRequest(
            scenario=scenario,
            client_information=client_information,
            conversation_history=_parse_chat(chat),
            product_ids=[],
            event_id=event_id if scenario == "活动邀请" else None,
            occasion=occasion,
            client_id=client_id,
            output_language=_LANGUAGE_OPTIONS.get(st.session_state.get(_LANG_KEY), "zh-CN"),
            tone=_TONE_OPTIONS.get(st.session_state.get(_TONE_KEY), "natural"),
            length=_LENGTH_OPTIONS.get(st.session_state.get(_LENGTH_KEY), "standard"),
            goal=_GOAL_OPTIONS.get(st.session_state.get(_GOAL_KEY), None),
        )
        previous_result = st.session_state.pop("active_result", None)
        try:
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

    _render_result()


def _render_result() -> None:
    active = st.session_state.get("active_result")
    if not active:
        return
    st.divider()
    st.markdown("**本次结果**")
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
        _render_candidate_card(active, index, candidate)
    st.caption("结构检查通过不代表内容已经通过人工评价。请核对人物、价格、规格和承诺。")


def _render_candidate_card(active: dict, index: int, candidate: dict) -> None:
    candidate_id = candidate["candidate_id"]
    draft_key = f"qixu-draft-{active['run_id']}-{candidate_id}"
    original = candidate["text"]
    with st.container(border=True):
        st.markdown(
            f'<div class="qixu-card-head"><span class="qixu-card-no">候选 {index}</span>'
            f'<span class="qixu-card-meta">一条完整微信消息 · 保存与复制均不会发送</span></div>',
            unsafe_allow_html=True)
        with st.expander(f"编辑 / 处理候选 {index}"):
            draft = st.text_area("编辑稿", value=original, height=150, key=draft_key)
            operator = st.text_input("顾问标识（可选，与客户分开记录）", key=f"qixu-operator-{active['run_id']}-{candidate_id}")
            action = st.radio("处理方式", ["保存编辑稿", "选用原稿", "弃用本组三条"], horizontal=True,
                key=f"qixu-action-{active['run_id']}-{candidate_id}")
            if st.button("保存处理记录", key=f"qixu-save-{active['run_id']}-{candidate_id}"):
                try:
                    actions = {"保存编辑稿": "edit", "选用原稿": "select", "弃用本组三条": "discard"}
                    save_feedback(active["run_id"], active["case_id"], None if action == "弃用本组三条" else candidate_id,
                        actions[action], edited_text=draft if action == "保存编辑稿" else "",
                        operator=operator or None, root=ROOT)
                    st.success("处理记录已保存；机器原稿保持原样。保存与复制均不会发送微信。")
                except (ValueError, OSError) as exc:
                    st.error(f"未保存：{exc}")
        st.markdown('<div class="qixu-card-divider"></div>', unsafe_allow_html=True)
        current_text = st.session_state.get(draft_key) or original
        body = html_lib.escape(current_text).replace("\n", "<br>")
        st.markdown(f'<div class="qixu-card-body">{body}</div>', unsafe_allow_html=True)
        _copy_button(current_text, f"qixu-copy-{active['run_id']}-{candidate_id}")
    st.caption("复制读取点击当下的正文；未保存的修改同样可复制。复制与保存都不是发送，当前没有微信发送。")


def evaluation_page() -> None:
    st.write("先阅读机器原稿，按固定要点逐条判断。这里仅保存真人填写的评价。")
    runs = sorted((ROOT / "artifacts/runs").glob("*/manifest.json"),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    eligible = [p.parent.name for p in runs if _read(p).get("execution_mode") == "real"]
    if not eligible:
        st.info("尚无真实运行记录。完成真实生成后，可在这里逐条评价；当前人工评分为零。")
        return
    def has_formal_snapshot(name: str) -> bool:
        plan_path = ROOT / "artifacts/runs" / name / "evaluation-plan.json"
        return plan_path.exists() and "case_manifest" in _read(plan_path)
    default_index = next((index for index, name in enumerate(eligible) if has_formal_snapshot(name)), 0)
    run_id = st.selectbox("待评价运行", eligible, index=default_index)
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
    st.set_page_config(page_title="栖序 QIXU · 顾问助手", layout="centered",
        menu_items={"Get help": None, "Report a bug": None, "About": "栖序 QIXU 顾问助手 · 资料均为虚构"})
    st.markdown(_CSS, unsafe_allow_html=True)
    _apply_dev_pending()
    _writing_settings()
    _model_status()
    with st.sidebar.expander("人工评价"):
        evaluation_page()
    _dev_cases()
    _brand_header()
    advisor_page()


if __name__ == "__main__":
    main()
