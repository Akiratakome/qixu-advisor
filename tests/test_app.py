"""Streamlit 真实表单路径 + 显式替身模型；仅在临时目录运行，不能证明模型质量。"""

import json
import shutil

from streamlit.testing.v1 import AppTest

from qixu_advisor import evaluation, generation, records


def test_form_submit_is_only_generation_trigger_and_edit_keeps_original(tmp_path, monkeypatch):
    source_root = evaluation.ROOT
    shutil.copytree(source_root / "data", tmp_path / "data")
    shutil.copytree(source_root / "src/qixu_advisor/prompts", tmp_path / "src/qixu_advisor/prompts")
    monkeypatch.setattr(evaluation, "ROOT", tmp_path)
    original_create, original_generate = records.create_run, generation.generate
    calls = []

    def stub_model(messages, config):
        calls.append(messages)
        return {"raw_text": json.dumps({"candidates": [{"text": f"这是离线表单测试候选{i}，祝您生日愉快。"} for i in (1, 2, 3)]}, ensure_ascii=False), "model": "explicit-test-stub", "usage": {}, "finish_reason": "stop"}

    def stub_create(case_ids, **kwargs):
        kwargs["execution_mode"] = "stub"
        return original_create(case_ids, **kwargs)

    def stub_generate(request, run_id, case_id, **kwargs):
        return original_generate(request, run_id, case_id, **kwargs, execution_mode="stub", model_call=stub_model)

    monkeypatch.setattr(records, "create_run", stub_create)
    monkeypatch.setattr(generation, "generate", stub_generate)
    app = AppTest.from_file(str(source_root / "src/qixu_advisor/app.py")).run()
    assert not app.exception
    assert not calls
    next(widget for widget in app.text_input if widget.label == "联系对象").input("测试客户")
    next(widget for widget in app.text_input if widget.label == "祝福缘由").input("今天生日")
    app.run()
    assert not calls
    # 模拟顾问完成表单再提交；单独重绘不等同于提交浏览器表单。
    next(widget for widget in app.text_input if widget.label == "联系对象").input("测试客户")
    next(widget for widget in app.text_input if widget.label == "祝福缘由").input("今天生日")
    next(button for button in app.button if button.label == "生成三条候选").click().run()
    assert not app.exception
    assert len(calls) == 1, ([e.value for e in app.error], app.session_state["active_result"])
    result_path = next((tmp_path / "artifacts/runs").glob("*/cases/UI-001/result.json"))
    original = result_path.read_bytes()
    app.run()
    assert len(calls) == 1
    next(widget for widget in app.text_area if widget.label == "编辑稿").input("人工改写的程序测试文本")
    next(button for button in app.button if button.label == "保存处理记录").click().run()
    assert not app.exception
    assert len(calls) == 1
    assert result_path.read_bytes() == original
    feedback = json.loads((result_path.parent / "feedback.jsonl").read_text(encoding="utf-8").strip())
    assert feedback["edited_text"] == "人工改写的程序测试文本"
    assert feedback["sent"] is False
    manifest = json.loads((result_path.parents[2] / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["execution_mode"] == "stub"
    first_run_id = manifest["run_id"]
    next(button for button in app.button if button.label == "生成三条候选").click().run()
    assert not app.exception
    assert len(calls) == 2
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
    source_root = evaluation.ROOT
    shutil.copytree(source_root / "data", tmp_path / "data")
    shutil.copytree(source_root / "src/qixu_advisor/prompts", tmp_path / "src/qixu_advisor/prompts")
    monkeypatch.setattr(evaluation, "ROOT", tmp_path)
    original_create, original_generate = records.create_run, generation.generate
    captured_requests = []

    def stub_model(messages, config):
        system = messages[0]["content"]
        if "英文（en）" in system:
            texts = [f"Offline form candidate {i} for stub testing only." for i in (1, 2, 3)]
        else:
            texts = [f"这是离线表单测试候选{i}，祝您生日愉快。" for i in (1, 2, 3)]
        return {"raw_text": json.dumps({"candidates": [{"text": text} for text in texts]}, ensure_ascii=False), "model": "explicit-test-stub", "usage": {}, "finish_reason": "stop"}

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
    next(widget for widget in app.text_input if widget.label == "联系对象").input("测试客户")
    next(widget for widget in app.text_input if widget.label == "祝福缘由").input("今天生日")
    next(widget for widget in app.selectbox if widget.label == "输出语言").select("English")
    next(widget for widget in app.selectbox if widget.label == "语气").select("温和")
    next(widget for widget in app.selectbox if widget.label == "篇幅").select("简短")
    next(widget for widget in app.selectbox if widget.label == "本次目标").select("提出下一步")
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
