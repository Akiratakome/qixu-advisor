"""Streamlit 工作台真实点击路径 + 显式替身模型；仅在临时目录运行，不能证明模型质量。"""

import json
import shutil

import pytest
from streamlit.testing.v1 import AppTest

from qixu_advisor import evaluation, generation, records
from qixu_advisor.data import load_cases

_ANALYSIS_PREFIX = "【分析】"


def _setup_app(tmp_path, monkeypatch):
    source_root = evaluation.ROOT
    shutil.copytree(source_root / "data", tmp_path / "data")
    shutil.copytree(source_root / "src/qixu_advisor/prompts", tmp_path / "src/qixu_advisor/prompts")
    monkeypatch.setattr(evaluation, "ROOT", tmp_path)
    monkeypatch.setenv("QIXU_RUNTIME_DIR", str(tmp_path / "runtime"))
    return source_root


def _analyze_stub(calls, scenario="生日与节庆", current_need="客户今天生日，希望送上生日祝福", missing=None):
    def stub(history, client_information, **kwargs):
        calls.append((history, client_information))
        return {"scenario": scenario, "current_need": current_need, "missing_questions": list(missing or [])}
    return stub


def _birthday_model_stub(calls):
    def stub_model(messages, config):
        calls.append(messages)
        return {"raw_text": json.dumps({"candidates": [{"text": f"这是离线表单测试候选{i}，祝您生日愉快。"} for i in (1, 2, 3)]}, ensure_ascii=False), "model": "explicit-test-stub", "usage": {}, "finish_reason": "stop"}
    return stub_model


def _install_generation_stubs(monkeypatch, model_calls, model_stub):
    original_create, original_generate = records.create_run, generation.generate

    def stub_create(case_ids, **kwargs):
        kwargs["execution_mode"] = "stub"
        return original_create(case_ids, **kwargs)

    def stub_generate(request, run_id, case_id, **kwargs):
        return original_generate(request, run_id, case_id, **kwargs, execution_mode="stub", model_call=model_stub)

    monkeypatch.setattr(records, "create_run", stub_create)
    monkeypatch.setattr(generation, "generate", stub_generate)


def test_generation_only_on_button_click_and_edit_keeps_original(tmp_path, monkeypatch):
    """只有点击「生成三条候选」才触发生成；重绘与编辑不调用模型；编辑保留机器原稿；失败可见。"""
    source_root = _setup_app(tmp_path, monkeypatch)
    analyze_calls, model_calls = [], []
    monkeypatch.setattr(generation, "analyze_conversation", _analyze_stub(analyze_calls))
    _install_generation_stubs(monkeypatch, model_calls, _birthday_model_stub(model_calls))
    app = AppTest.from_file(str(source_root / "src/qixu_advisor/app.py")).run()
    assert not app.exception
    assert not model_calls and not analyze_calls
    next(widget for widget in app.text_area if widget.label == "对话记录（每行一条）").input("客户：今天是我生日。")
    app.run()
    assert not app.exception
    assert not model_calls and not analyze_calls
    next(button for button in app.button if button.label == "分析并提问").click().run()
    assert not app.exception
    assert len(analyze_calls) == 1
    assert len(model_calls) == 0
    next(button for button in app.button if button.label == "生成三条候选").click().run()
    assert not app.exception
    assert len(model_calls) == 1, ([e.value for e in app.error], app.session_state["active_result"])
    result_path = next((tmp_path / "artifacts/runs").glob("*/cases/UI-001/result.json"))
    original = result_path.read_bytes()
    app.run()
    assert len(model_calls) == 1 and len(analyze_calls) == 1
    next(widget for widget in app.text_area if widget.label == "编辑稿").input("人工改写的程序测试文本")
    next(button for button in app.button if button.label == "保存处理记录").click().run()
    assert not app.exception
    assert len(model_calls) == 1
    assert result_path.read_bytes() == original
    feedback = json.loads((result_path.parent / "feedback.jsonl").read_text(encoding="utf-8").strip())
    assert feedback["edited_text"] == "人工改写的程序测试文本"
    assert feedback["sent"] is False
    manifest = json.loads((result_path.parents[2] / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["execution_mode"] == "stub"
    first_run_id = manifest["run_id"]
    next(button for button in app.button if button.label == "生成三条候选").click().run()
    assert not app.exception
    assert len(model_calls) == 2
    next_run_id = app.session_state["active_result"]["run_id"]
    next_manifest = json.loads((tmp_path / "artifacts/runs" / next_run_id / "manifest.json").read_text(encoding="utf-8"))
    assert next_manifest["parent_run_id"] == first_run_id
    assert result_path.read_bytes() == original

    def rejected_generate(*args, **kwargs):
        raise ValueError("程序测试：新请求保存失败")

    monkeypatch.setattr(generation, "generate", rejected_generate)
    next(button for button in app.button if button.label == "生成三条候选").click().run()
    assert not app.exception
    assert not any(widget.label == "编辑稿" for widget in app.text_area)
    assert any("新请求保存失败" in error.value for error in app.error)


def test_writing_settings_controls_pass_to_request(tmp_path, monkeypatch):
    """侧栏写作设置默认值存在，且选择后的值传入 GenerationRequest 与有效设置。"""
    source_root = _setup_app(tmp_path, monkeypatch)
    analyze_calls, model_calls = [], []
    monkeypatch.setattr(generation, "analyze_conversation", _analyze_stub(analyze_calls))
    captured_requests = []

    def stub_model(messages, config):
        model_calls.append(messages)
        system = messages[0]["content"]
        if "英文（en）" in system:
            texts = [f"Offline form candidate {i} for stub testing only." for i in (1, 2, 3)]
        else:
            texts = [f"这是离线表单测试候选{i}，祝您生日愉快。" for i in (1, 2, 3)]
        return {"raw_text": json.dumps({"candidates": [{"text": text} for text in texts]}, ensure_ascii=False), "model": "explicit-test-stub", "usage": {}, "finish_reason": "stop"}

    original_create, original_generate = records.create_run, generation.generate

    def stub_create(case_ids, **kwargs):
        kwargs["execution_mode"] = "stub"
        return original_create(case_ids, **kwargs)

    def stub_generate(request, run_id, case_id, **kwargs):
        captured_requests.append(request)
        return original_generate(request, run_id, case_id, **kwargs, execution_mode="stub", model_call=stub_model)

    monkeypatch.setattr(records, "create_run", stub_create)
    monkeypatch.setattr(generation, "generate", stub_generate)
    app = AppTest.from_file(str(source_root / "src/qixu_advisor/app.py")).run()
    assert not app.exception
    settings = {widget.label: widget for widget in app.sidebar.selectbox}
    assert {"输出语言", "语气", "篇幅", "本次目标"} <= set(settings)
    assert settings["输出语言"].value == "中文"
    assert settings["语气"].value == "自然"
    assert settings["篇幅"].value == "标准"
    assert settings["本次目标"].value == "按场景默认"
    next(widget for widget in app.text_area if widget.label == "对话记录（每行一条）").input("客户：今天是我生日。")
    next(button for button in app.button if button.label == "分析并提问").click().run()
    assert not app.exception
    settings = {widget.label: widget for widget in app.sidebar.selectbox}
    settings["输出语言"].select("English")
    settings["语气"].select("温和")
    settings["篇幅"].select("简短")
    settings["本次目标"].select("提出下一步")
    next(button for button in app.button if button.label == "生成三条候选").click().run()
    assert not app.exception
    assert len(captured_requests) == 1
    request = captured_requests[0]
    assert request.output_language == "en"
    assert request.tone == "warm"
    assert request.length == "short"
    assert request.goal == "next_step"
    active = app.session_state["active_result"]
    assert active["status"] == "success"
    assert active["provenance"]["effective_settings"]["output_language"] == "en"


def test_analysis_button_triggers_stub_and_failure_visible(tmp_path, monkeypatch):
    """只有点击「分析并提问」才调用分析；重绘不重复调用；分析失败原因可见。"""
    source_root = _setup_app(tmp_path, monkeypatch)
    analyze_calls = []
    monkeypatch.setattr(generation, "analyze_conversation",
        _analyze_stub(analyze_calls, scenario="产品推荐", current_need="为妹妹挑选一款清爽的香水",
            missing=["她平时喜欢哪类气味？", "预算范围是多少？"]))
    app = AppTest.from_file(str(source_root / "src/qixu_advisor/app.py")).run()
    assert not app.exception
    assert not analyze_calls
    assert not any(widget.label == "生成三条候选" for widget in app.button)
    next(widget for widget in app.text_area if widget.label == "对话记录（每行一条）").input("客户：想给妹妹挑一款香水。")
    app.run()
    assert not app.exception
    assert not analyze_calls
    next(button for button in app.button if button.label == "分析并提问").click().run()
    assert not app.exception
    assert len(analyze_calls) == 1
    history, client_information = analyze_calls[0]
    assert history == [{"role": "client", "content": "想给妹妹挑一款香水。"}]
    assert client_information == {}
    assert any(widget.label == "识别场景（可调整）" and widget.value == "产品推荐" for widget in app.selectbox)
    assert any("为妹妹挑选一款清爽的香水" in info.value for info in app.info)
    assert any("她平时喜欢哪类气味？" in widget.value for widget in app.markdown)
    assert any(button.label == "生成三条候选" for button in app.button)
    app.run()
    assert not app.exception
    assert len(analyze_calls) == 1

    def broken(*args, **kwargs):
        raise ValueError("程序测试：分析失败")

    monkeypatch.setattr(generation, "analyze_conversation", broken)
    next(button for button in app.button if button.label == "分析并提问").click().run()
    assert not app.exception
    assert any("分析未完成" in error.value and "程序测试：分析失败" in error.value for error in app.error)
    assert len(analyze_calls) == 1


def test_copy_components_present_with_live_draft(tmp_path, monkeypatch):
    """三张候选卡各有一个复制组件；未保存的修改也会进入复制内容。"""
    source_root = _setup_app(tmp_path, monkeypatch)
    analyze_calls, model_calls = [], []
    monkeypatch.setattr(generation, "analyze_conversation", _analyze_stub(analyze_calls))
    _install_generation_stubs(monkeypatch, model_calls, _birthday_model_stub(model_calls))
    app = AppTest.from_file(str(source_root / "src/qixu_advisor/app.py")).run()
    next(widget for widget in app.text_area if widget.label == "对话记录（每行一条）").input("客户：今天是我生日。")
    next(button for button in app.button if button.label == "分析并提问").click().run()
    next(button for button in app.button if button.label == "生成三条候选").click().run()
    assert not app.exception
    active = app.session_state["active_result"]
    assert active["status"] == "success"
    iframes = app.get("iframe")
    assert len(iframes) == 3
    for iframe in iframes:
        srcdoc = iframe.proto.srcdoc
        assert "navigator.clipboard" in srcdoc and "writeText" in srcdoc
    texts = [candidate["text"] for candidate in active["candidates"]]
    for text in texts:
        assert any(text in iframe.proto.srcdoc for iframe in iframes)
    next(widget for widget in app.text_area if widget.label == "编辑稿").input("未保存的修改稿")
    app.run()
    assert not app.exception
    assert any("未保存的修改稿" in iframe.proto.srcdoc for iframe in app.get("iframe"))


def test_dev_cases_hidden_until_opted_in(tmp_path, monkeypatch):
    """开发案例默认不可见；勾选「显示开发案例（内部）」后才出现案例选择，可载入到主区。"""
    source_root = _setup_app(tmp_path, monkeypatch)
    app = AppTest.from_file(str(source_root / "src/qixu_advisor/app.py")).run()
    assert not app.exception
    assert not any(widget.label == "选择案例" for widget in app.sidebar.selectbox)
    checkbox = next(widget for widget in app.sidebar.checkbox if widget.label == "显示开发案例（内部）")
    assert checkbox.value is False
    checkbox.check().run()
    assert not app.exception
    selectors = [widget for widget in app.sidebar.selectbox if widget.label == "选择案例"]
    assert len(selectors) == 1
    assert any(button.label == "载入到主区" for button in app.sidebar.button)
    cases = [case for case in load_cases("dev") if case.request.conversation_history]
    assert cases
    target = cases[0]
    selectors[0].select_index(next(index for index, case in enumerate(load_cases("dev")) if case.case_id == target.case_id))
    next(button for button in app.sidebar.button if button.label == "载入到主区").click().run()
    assert not app.exception
    chat = next(widget for widget in app.text_area if widget.label == "对话记录（每行一条）")
    assert chat.value.strip()


def test_conversation_create_select_restore_and_message_persistence(tmp_path, monkeypatch):
    """新建会话→分析后消息与分析结果落库；重开应用选中会话可恢复对话（不含内部分析行）。"""
    storage = pytest.importorskip("qixu_advisor.storage")
    source_root = _setup_app(tmp_path, monkeypatch)
    analyze_calls = []
    monkeypatch.setattr(generation, "analyze_conversation", _analyze_stub(analyze_calls))
    app = AppTest.from_file(str(source_root / "src/qixu_advisor/app.py")).run()
    assert not app.exception
    next(button for button in app.sidebar.button if button.label == "新建会话").click().run()
    assert not app.exception
    conversation_id = app.session_state["selected_conversation_id"]
    assert conversation_id
    next(widget for widget in app.text_area if widget.label == "对话记录（每行一条）").input("客户：想给妹妹挑一款香水。")
    next(button for button in app.button if button.label == "分析并提问").click().run()
    assert not app.exception
    assert len(analyze_calls) == 1
    conn = storage.connect_db()
    try:
        messages = storage.list_messages(conn, conversation_id)
    finally:
        conn.close()
    assert [(m["role"], m["source"], m["content"]) for m in messages] == [
        ("client", "manual", "想给妹妹挑一款香水。"),
        ("advisor", "workbench", f"{_ANALYSIS_PREFIX}场景：生日与节庆；本次需求：客户今天生日，希望送上生日祝福"),
    ]
    # 重开应用：会话列表存在，选中后恢复对话，内部分析行不回填主区。
    app2 = AppTest.from_file(str(source_root / "src/qixu_advisor/app.py")).run()
    assert not app.exception
    selector = next(widget for widget in app2.sidebar.selectbox if widget.label == "当前会话")
    assert selector.value is None
    selector.select_index(1).run()
    assert not app.exception
    chat = next(widget for widget in app2.text_area if widget.label == "对话记录（每行一条）")
    assert chat.value == "客户：想给妹妹挑一款香水。"
    assert _ANALYSIS_PREFIX not in chat.value


def test_generation_draft_revisions_and_actions_recorded(tmp_path, monkeypatch):
    """生成记录、三条草稿修订与编辑/选用/弃用/复制动作在数据库中留证。"""
    storage = pytest.importorskip("qixu_advisor.storage")
    source_root = _setup_app(tmp_path, monkeypatch)
    analyze_calls, model_calls = [], []
    monkeypatch.setattr(generation, "analyze_conversation", _analyze_stub(analyze_calls))
    _install_generation_stubs(monkeypatch, model_calls, _birthday_model_stub(model_calls))
    app = AppTest.from_file(str(source_root / "src/qixu_advisor/app.py")).run()
    next(button for button in app.sidebar.button if button.label == "新建会话").click().run()
    next(widget for widget in app.text_area if widget.label == "对话记录（每行一条）").input("客户：今天是我生日。")
    next(button for button in app.button if button.label == "分析并提问").click().run()
    next(button for button in app.button if button.label == "生成三条候选").click().run()
    assert not app.exception
    conn = storage.connect_db()
    try:
        generations = conn.execute("SELECT * FROM generations ORDER BY created_at").fetchall()
        assert len(generations) == 1
        assert generations[0]["status"] == "success"
        assert generations[0]["run_id"] and generations[0]["case_id"] == "UI-001"
        revisions = conn.execute("SELECT * FROM draft_revisions ORDER BY id").fetchall()
        assert len(revisions) == 3
        assert {row["revision"] for row in revisions} == {1}
    finally:
        conn.close()
    # 选用原稿（基准修订 1）
    next(widget for widget in app.radio if widget.label == "处理方式").set_value("选用原稿")
    next(button for button in app.button if button.label == "保存处理记录").click().run()
    assert not app.exception
    # 编辑候选 1（追加修订 2）
    next(widget for widget in app.radio if widget.label == "处理方式").set_value("保存编辑稿")
    next(widget for widget in app.text_area if widget.label == "编辑稿").input("人工改写的程序测试文本")
    next(button for button in app.button if button.label == "保存处理记录").click().run()
    assert not app.exception
    # 弃用本组三条
    next(widget for widget in app.radio if widget.label == "处理方式").set_value("弃用本组三条")
    next(button for button in app.button if button.label == "保存处理记录").click().run()
    assert not app.exception
    conn = storage.connect_db()
    try:
        rows = conn.execute(
            "SELECT a.action, a.copied_text, r.revision, r.candidate_id "
            "FROM draft_actions a JOIN draft_revisions r ON r.id = a.draft_revision_id ORDER BY a.id").fetchall()
        actions = [(row["action"], row["revision"], row["candidate_id"], row["copied_text"]) for row in rows]
        assert ("selected", 1, "UI-001-C1", "") in actions
        discarded = [item for item in actions if item[0] == "discarded"]
        assert len(discarded) == 3
        assert {(item[1], item[2]) for item in discarded} == {(2, "UI-001-C1"), (1, "UI-001-C2"), (1, "UI-001-C3")}
        revisions = conn.execute("SELECT candidate_id, revision, text FROM draft_revisions ORDER BY id").fetchall()
        assert any(row["candidate_id"] == "UI-001-C1" and row["revision"] == 2 and row["text"] == "人工改写的程序测试文本" for row in revisions)
    finally:
        conn.close()


def test_copy_action_recorded_with_live_draft(tmp_path, monkeypatch):
    """复制留证：未保存的编辑稿按实际复制文本与基准修订记 copied 动作。"""
    storage = pytest.importorskip("qixu_advisor.storage")
    source_root = _setup_app(tmp_path, monkeypatch)
    analyze_calls, model_calls = [], []
    monkeypatch.setattr(generation, "analyze_conversation", _analyze_stub(analyze_calls))
    _install_generation_stubs(monkeypatch, model_calls, _birthday_model_stub(model_calls))
    app = AppTest.from_file(str(source_root / "src/qixu_advisor/app.py")).run()
    next(button for button in app.sidebar.button if button.label == "新建会话").click().run()
    next(widget for widget in app.text_area if widget.label == "对话记录（每行一条）").input("客户：今天是我生日。")
    next(button for button in app.button if button.label == "分析并提问").click().run()
    next(button for button in app.button if button.label == "生成三条候选").click().run()
    assert not app.exception
    next(widget for widget in app.text_area if widget.label == "编辑稿").input("未保存的修改稿")
    next(button for button in app.button if button.label == "复制本候选").click().run()
    assert not app.exception
    conn = storage.connect_db()
    try:
        rows = conn.execute(
            "SELECT a.action, a.copied_text, r.revision, r.candidate_id "
            "FROM draft_actions a JOIN draft_revisions r ON r.id = a.draft_revision_id").fetchall()
    finally:
        conn.close()
    copied = [(row["action"], row["revision"], row["candidate_id"], row["copied_text"]) for row in rows]
    assert copied == [("copied", 1, "UI-001-C1", "未保存的修改稿")]


def test_preferences_confirm_revoke_and_add(tmp_path, monkeypatch):
    """偏好表格、确认/撤销与新增小表单落库。"""
    storage = pytest.importorskip("qixu_advisor.storage")
    source_root = _setup_app(tmp_path, monkeypatch)
    (tmp_path / "runtime").mkdir(parents=True, exist_ok=True)
    conn = storage.connect_db()
    try:
        storage.init_schema(conn)
        storage.add_preference(conn, "C001", "dislike", "不喜欢浓郁花香", False, "workbench")
    finally:
        conn.close()
    app = AppTest.from_file(str(source_root / "src/qixu_advisor/app.py")).run()
    assert not app.exception
    tables = app.sidebar.get("table")
    assert len(tables) == 1
    assert "不喜欢浓郁花香" in tables[0].value.to_string()
    next(button for button in app.sidebar.button if button.label == "确认").click().run()
    assert not app.exception
    next(button for button in app.sidebar.button if button.label == "撤销").click().run()
    assert not app.exception
    next(widget for widget in app.sidebar.text_input if widget.label == "主体").input("C002")
    next(widget for widget in app.sidebar.text_input if widget.label == "原文").input("预算一千左右")
    next(widget for widget in app.sidebar.selectbox if widget.label == "类别").select_index(2)
    next(widget for widget in app.sidebar.radio if widget.label == "来源性质").set_value("推测")
    next(button for button in app.sidebar.form_submit_button if button.label == "保存偏好").click().run()
    assert not app.exception
    conn = storage.connect_db()
    try:
        rows = conn.execute("SELECT * FROM preferences ORDER BY id").fetchall()
    finally:
        conn.close()
    assert len(rows) == 2
    assert rows[0]["status"] == "revoked"
    added = rows[1]
    assert added["subject"] == "C002"
    assert added["kind"] == "budget"
    assert added["original_text"] == "预算一千左右"
    assert added["explicit"] == 0
    assert added["status"] == "pending"
