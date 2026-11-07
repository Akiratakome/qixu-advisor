"""写作设置、提示组装与事实告警的离线检查；模型一律显式替身，不调用真实 API。"""

import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from qixu_advisor.data import PROJECT_ROOT, load_cases, load_facts
from qixu_advisor.generation import build_messages, check_explicit_facts, generate
from qixu_advisor.models import Candidate, GenerationRequest
from qixu_advisor.records import create_run


@pytest.fixture
def isolated_root(tmp_path: Path) -> Path:
    shutil.copytree(PROJECT_ROOT / "data" / "fictional", tmp_path / "data" / "fictional")
    shutil.copytree(PROJECT_ROOT / "src" / "qixu_advisor", tmp_path / "src" / "qixu_advisor", ignore=shutil.ignore_patterns("__pycache__"))
    return tmp_path


def chinese_stub() -> dict:
    return {"raw_text": json.dumps({"candidates": [{"text": "测试替身第一条：这只用于检查程序结构。"}, {"text": "测试替身第二条：这些文字不是模型实测。"}, {"text": "测试替身第三条：不要将其作为正式业务输出。"}]}, ensure_ascii=False), "model": "offline-test-stub", "usage": {}, "elapsed_seconds": 0, "finish_reason": "stop"}


def english_stub() -> dict:
    return {"raw_text": json.dumps({"candidates": [{"text": f"Offline stub candidate {i}: English placeholder for structural tests only."} for i in (1, 2, 3)]}, ensure_ascii=False), "model": "offline-test-stub", "usage": {}, "elapsed_seconds": 0, "finish_reason": "stop"}


def ascii_stub() -> dict:
    return {"raw_text": json.dumps({"candidates": [{"text": "Pure ASCII candidate one."}, {"text": "Pure ASCII candidate two."}, {"text": "Pure ASCII candidate three."}]}, ensure_ascii=False), "model": "offline-test-stub", "usage": {}, "elapsed_seconds": 0, "finish_reason": "stop"}


def test_generation_request_settings_defaults():
    request = GenerationRequest(scenario="产品推荐")
    assert request.output_language == "zh-CN"
    assert request.tone == "natural"
    assert request.length == "standard"
    assert request.goal is None


@pytest.mark.parametrize("field,value", [
    ("output_language", "fr"),
    ("tone", "angry"),
    ("length", "long"),
    ("goal", "sell"),
])
def test_generation_request_rejects_invalid_settings(field, value):
    with pytest.raises(ValidationError):
        GenerationRequest(scenario="产品推荐", **{field: value})


def test_existing_case_jsonl_gets_setting_defaults():
    for case in load_cases("all"):
        assert case.request.output_language == "zh-CN"
        assert case.request.tone == "natural"
        assert case.request.length == "standard"
        assert case.request.goal is None


def test_zh_candidates_without_cjk_are_rejected(isolated_root: Path):
    run = create_run(["CASE-1"], root=isolated_root, execution_mode="stub")
    result = generate(GenerationRequest(scenario="生日与节庆", occasion="生日"), run, "CASE-1", root=isolated_root, model_call=lambda *args: ascii_stub(), execution_mode="stub")
    assert result.status == "technical_failure"
    assert "输出语言设置" in result.error
    attempt = json.loads((isolated_root / "artifacts/runs" / run / "cases/CASE-1/attempts.jsonl").read_text(encoding="utf-8"))
    assert attempt["raw_text"] == ascii_stub()["raw_text"]


def test_en_candidates_all_ascii_are_accepted(isolated_root: Path):
    run = create_run(["CASE-1"], root=isolated_root, execution_mode="stub")
    result = generate(GenerationRequest(scenario="生日与节庆", occasion="生日", output_language="en"), run, "CASE-1", root=isolated_root, model_call=lambda *args: english_stub(), execution_mode="stub")
    assert result.status == "success"
    assert len(result.candidates) == 3
    assert result.provenance["effective_settings"]["output_language"] == "en"


def test_en_candidates_without_ascii_letters_are_rejected(isolated_root: Path):
    run = create_run(["CASE-1"], root=isolated_root, execution_mode="stub")
    result = generate(GenerationRequest(scenario="生日与节庆", occasion="生日", output_language="en"), run, "CASE-1", root=isolated_root, model_call=lambda *args: chinese_stub(), execution_mode="stub")
    assert result.status == "technical_failure"
    assert "输出语言设置" in result.error


@pytest.mark.parametrize("scenario,expected_goal", [
    ("生日与节庆", "answer"),
    ("产品推荐", "recommend"),
    ("购后关怀", "answer"),
    ("沉睡唤醒", "next_step"),
    ("活动邀请", "next_step"),
    ("价格异议", "answer"),
])
def test_effective_settings_resolve_scenario_default_goal(isolated_root: Path, scenario: str, expected_goal: str):
    request = GenerationRequest(scenario=scenario, client_information={"current_need": "希望了解现有资料"}, occasion="生日", event_id="EVT-CITRUS")
    run = create_run(["CASE-1"], root=isolated_root, execution_mode="stub")
    result = generate(request, run, "CASE-1", root=isolated_root, model_call=lambda *args: chinese_stub(), execution_mode="stub")
    settings = result.provenance["effective_settings"]
    assert settings["goal"] == expected_goal
    assert settings["goal_source"] == "scenario_default"


def test_build_messages_includes_rules_and_settings(isolated_root: Path):
    rules = isolated_root / "src/qixu_advisor/prompts/writing_rules.md"
    rules.write_text("# 写作规则\n- 事实先于文风。\n", encoding="utf-8")
    request = GenerationRequest(scenario="产品推荐", output_language="en", tone="direct", length="short")
    messages = build_messages(request, load_facts(request, root=isolated_root), root=isolated_root)
    system = messages[0]["content"]
    base = (isolated_root / "src/qixu_advisor/prompts/system.txt").read_text(encoding="utf-8")
    assert system.startswith(base)
    # 加载机制追加的【写作规则】段必须位于 system.txt 之后。
    assert system.count("【写作规则】") == base.count("【写作规则】") + 1
    rules_pos = system.index("【写作规则】", len(base))
    settings_pos = system.index("【写作设置】", len(base))
    scene_pos = system.index("本场景要求：", len(base))
    assert rules_pos < settings_pos < scene_pos
    settings_block = system[settings_pos:scene_pos]
    assert "事实先于文风" in system
    assert "- 输出语言：英文（en）" in settings_block
    assert "- 语气：直接" in settings_block
    assert "- 篇幅：简短" in settings_block
    assert "- 本次目标：帮助选择（场景默认）" in settings_block


def test_build_messages_without_rules_file_skips_section(isolated_root: Path):
    rules = isolated_root / "src/qixu_advisor/prompts/writing_rules.md"
    if rules.exists():
        rules.unlink()
    request = GenerationRequest(scenario="生日与节庆", occasion="生日", goal="answer")
    messages = build_messages(request, load_facts(request, root=isolated_root), root=isolated_root)
    system = messages[0]["content"]
    base = (isolated_root / "src/qixu_advisor/prompts/system.txt").read_text(encoding="utf-8")
    assert system.count("【写作规则】") == base.count("【写作规则】")
    settings_block = system[system.index("【写作设置】", len(base)):system.index("本场景要求：", len(base))]
    assert "- 本次目标：回答问题" in settings_block
    assert "（场景默认）" not in settings_block


def test_approved_examples_missing_file_is_skipped(isolated_root: Path):
    request = GenerationRequest(scenario="生日与节庆", occasion="生日")
    messages = build_messages(request, load_facts(request, root=isolated_root), root=isolated_root)
    assert "【经审阅参考示例】" not in messages[0]["content"]


def test_approved_examples_empty_file_is_skipped(isolated_root: Path):
    examples_dir = isolated_root / "data/style_examples"
    examples_dir.mkdir(parents=True)
    (examples_dir / "approved.jsonl").write_text("", encoding="utf-8")
    request = GenerationRequest(scenario="生日与节庆", occasion="生日")
    messages = build_messages(request, load_facts(request, root=isolated_root), root=isolated_root)
    assert "【经审阅参考示例】" not in messages[0]["content"]


def test_approved_examples_non_empty_injected(isolated_root: Path):
    examples_dir = isolated_root / "data/style_examples"
    examples_dir.mkdir(parents=True)
    (examples_dir / "approved.jsonl").write_text(
        '{"scenario":"生日与节庆","text":"祝您生日快乐，愿新的一岁顺心如意。"}\n'
        '{"text":"第二条参考示例。"}\n', encoding="utf-8")
    request = GenerationRequest(scenario="生日与节庆", occasion="生日")
    messages = build_messages(request, load_facts(request, root=isolated_root), root=isolated_root)
    system = messages[0]["content"]
    assert "【经审阅参考示例】" in system
    assert "愿新的一岁顺心如意" in system
    assert "第二条参考示例" in system


def test_approved_examples_invalid_json_line_raises(isolated_root: Path):
    examples_dir = isolated_root / "data/style_examples"
    examples_dir.mkdir(parents=True)
    (examples_dir / "approved.jsonl").write_text('{"text":"合法示例"}\n不是 JSON 的行\n', encoding="utf-8")
    request = GenerationRequest(scenario="生日与节庆", occasion="生日")
    with pytest.raises(ValueError, match="第 2 行"):
        build_messages(request, load_facts(request, root=isolated_root), root=isolated_root)


def test_approved_examples_invalid_structure_raises(isolated_root: Path):
    examples_dir = isolated_root / "data/style_examples"
    examples_dir.mkdir(parents=True)
    (examples_dir / "approved.jsonl").write_text('["只有列表没有text字段"]\n', encoding="utf-8")
    request = GenerationRequest(scenario="生日与节庆", occasion="生日")
    with pytest.raises(ValueError, match="结构非法"):
        build_messages(request, load_facts(request, root=isolated_root), root=isolated_root)


def test_product_name_typo_warning(isolated_root: Path):
    request = GenerationRequest(scenario="产品推荐", client_information={"current_need": "想要柑橘香"}, product_ids=["QINGLAN"])
    facts = load_facts(request, root=isolated_root)
    candidate = Candidate(candidate_id="T", text="青澜50毫升是980元，柑橘气息很适合您。")
    warnings = check_explicit_facts([candidate], facts, request)
    assert any("疑似商品名错字：青澜（资料规范名：青岚）" in warning for warning in warnings)


def test_product_name_typo_present_in_materials_not_flagged(isolated_root: Path):
    request = GenerationRequest(scenario="产品推荐", client_information={"current_need": "客户提到过青澜"}, product_ids=["QINGLAN"])
    facts = load_facts(request, root=isolated_root)
    candidate = Candidate(candidate_id="T", text="青澜50毫升是980元。")
    assert check_explicit_facts([candidate], facts, request) == []


def test_budget_whitelist_suppresses_client_amount(isolated_root: Path):
    request = GenerationRequest(scenario="价格异议", client_information={"current_need": "预算最多1400元", "budget_cny": 1400},
        conversation_history=[{"role": "client", "content": "100毫升看着单价低，但我这次最多花1400。"}],
        product_ids=["QINGLAN-50", "QINGLAN-100"])
    facts = load_facts(request, root=isolated_root)
    candidate = Candidate(candidate_id="T", text="青岚50毫升是980元，在您1400元的预算内。")
    assert check_explicit_facts([candidate], facts, request) == []


def test_non_whitelisted_mismatched_amount_still_warned(isolated_root: Path):
    request = GenerationRequest(scenario="价格异议", client_information={"current_need": "觉得贵", "budget_cny": 1400},
        product_ids=["QINGLAN-50"])
    facts = load_facts(request, root=isolated_root)
    candidate = Candidate(candidate_id="T", text="青岚50毫升总价1600元。")
    warnings = check_explicit_facts([candidate], facts, request)
    assert any("请核对是品牌报价还是顾客原话" in warning for warning in warnings)
    assert any("该金额未在本次资料中出现" in warning for warning in warnings)


def test_history_amounts_are_whitelisted(isolated_root: Path):
    request = GenerationRequest(scenario="价格异议", client_information={"current_need": "想要青岚"},
        conversation_history=[{"role": "client", "content": "我最多出1600块。"}], product_ids=["QINGLAN-50"])
    facts = load_facts(request, root=isolated_root)
    candidate = Candidate(candidate_id="T", text="青岚50毫升总价1600元，在您提到的范围内。")
    assert check_explicit_facts([candidate], facts, request) == []


def test_unowned_amount_warning(isolated_root: Path):
    request = GenerationRequest(scenario="价格异议", client_information={"current_need": "希望了解"}, product_ids=["YUBAI-50"])
    facts = load_facts(request, root=isolated_root)
    candidate = Candidate(candidate_id="T", text="雨白50毫升是1180元，现在购买还送价值88元的赠品。")
    warnings = check_explicit_facts([candidate], facts, request)
    assert any("该金额未在本次资料中出现" in warning and "88" in warning for warning in warnings)
