"""去 AI 味插件（de_ai）的离线检查：纯函数规则 + generate 集成门槛；模型一律显式替身。"""

import json
import shutil
from pathlib import Path

import pytest

from qixu_advisor.data import PROJECT_ROOT
from qixu_advisor.de_ai import clean_text, lint_text
from qixu_advisor.generation import generate
from qixu_advisor.models import GenerationRequest, GenerationResult
from qixu_advisor.records import create_run


@pytest.fixture
def isolated_root(tmp_path: Path) -> Path:
    shutil.copytree(PROJECT_ROOT / "data" / "fictional", tmp_path / "data" / "fictional")
    shutil.copytree(PROJECT_ROOT / "src" / "qixu_advisor", tmp_path / "src" / "qixu_advisor", ignore=shutil.ignore_patterns("__pycache__"))
    return tmp_path


def de_ai_stub(texts: list[str]) -> dict:
    return {"raw_text": json.dumps({"candidates": [{"text": text} for text in texts]}, ensure_ascii=False), "model": "offline-de-ai-stub", "usage": {}, "elapsed_seconds": 0, "finish_reason": "stop"}


def categories(hits: list[dict]) -> set[str]:
    return {hit["category"] for hit in hits}


# ---------- lint_text ----------

@pytest.mark.parametrize("text,category,needle", [
    ("如还有其他需要请随时联系我。", "万能结尾", "如还有其他需要请随时联系我"),
    ("很高兴为您服务，关于价格的问题。", "客服开场", "很高兴为您服务"),
    ("关于您提到的预算，价格980元。", "总起句", "关于您提到的"),
    ("需要说明的是，价格不变。", "插入语", "需要说明的是"),
    ("不是清仓，而是库存不足。", "负面平行", "不是"),
    ("这款香诠释了木质调。", "意义后缀", "诠释了"),
    ("在这特别的日子里，祝您顺心。", "抒情堆砌", "在这特别的日子里"),
    ("我们打造了沉浸式试香体验。", "AI词表", "打造"),
])
def test_lint_patterns_hit(text, category, needle):
    hits = lint_text(text)
    assert category in categories(hits)
    hit = next(hit for hit in hits if hit["category"] == category)
    assert needle in hit["match"]
    assert hit["message"]


def test_lint_ai_vocabulary_reports_each_word():
    hits = lint_text("我们打造了沉浸式试香体验，形成品牌闭环。")
    matches = [hit["match"] for hit in hits if hit["category"] == "AI词表"]
    assert "打造" in matches and "沉浸式" in matches and "闭环" in matches


def test_lint_three_wishes_in_one_sentence():
    hits = lint_text("愿您幸福，愿您安康，愿您顺心。")
    assert "祝福叠愿" in categories(hits)


def test_lint_two_wishes_no_hit():
    assert "祝福叠愿" not in categories(lint_text("愿您幸福，也愿您安康。"))


def test_lint_tilde_density():
    hits = lint_text("好的呢～没问题哈～")
    assert any(hit["category"] == "语气词密度" and "～" in hit["message"] for hit in hits)


def test_lint_tone_tail_density():
    hits = lint_text("好的啦，没问题哈，再见哦。")
    assert any(hit["category"] == "语气词密度" and "句尾语气词" in hit["message"] for hit in hits)


def test_lint_normal_message_no_hits():
    assert lint_text("青岚50毫升是980元，柑橘与雪松气息，可以到店试闻。") == []
    assert lint_text("生日快乐，祝您生日愉快！") == []


def test_lint_hits_sorted_by_position():
    hits = lint_text("很高兴为您服务，祝您生活愉快！")
    assert [hit["category"] for hit in hits] == ["客服开场", "万能结尾"]


# ---------- clean_text ----------

def test_clean_removes_closing_sentence_with_leading_comma():
    cleaned, applied = clean_text("前面的内容，祝您生活愉快！")
    assert cleaned == "前面的内容"
    assert applied == ["万能结尾"]


def test_clean_removes_closing_after_semicolon():
    cleaned, applied = clean_text("价格980元；期待您的回复。")
    assert cleaned == "价格980元"
    assert applied == ["万能结尾"]


def test_clean_removes_opener_and_filler():
    assert clean_text("很高兴为您服务，价格980元。") == ("价格980元。", ["客服开场"])
    assert clean_text("需要说明的是，价格不变。") == ("价格不变。", ["插入语"])


def test_clean_combined_applied_order_and_semantics():
    cleaned, applied = clean_text("很高兴为您服务，关于您提到的预算问题，价格980元，祝您生活愉快！")
    assert cleaned == "关于您提到的预算问题，价格980元"
    assert applied == ["万能结尾", "客服开场"]


def test_clean_keeps_phrase_that_continues_sentence():
    # 「希望能帮到您」后还有正文时不清洗，避免改变语义。
    original = "希望能帮到您选到合适的香。"
    assert clean_text(original) == (original, [])


def test_clean_normal_message_untouched():
    original = "青岚50毫升是980元，柑橘与雪松气息。"
    assert clean_text(original) == (original, [])


def test_clean_empty_after_removal():
    assert clean_text("祝您生活愉快！") == ("", ["万能结尾"])


def test_clean_collapses_double_comma():
    cleaned, _ = clean_text("内容，很高兴为您服务，价格980元。")
    assert cleaned == "内容，价格980元。"


# ---------- generate 集成 ----------

def test_generate_applies_de_ai_gate_and_keeps_raw(isolated_root: Path):
    raw_texts = [
        "很高兴为您服务，关于您提到的预算问题，青岚50毫升是980元，祝您生活愉快！",
        "青岚100毫升是1580元，您可以先到店试闻。",
        "祝您生活愉快！期待您的回复。",
    ]
    request = GenerationRequest(scenario="产品推荐", client_information={"current_need": "想了解青岚"}, product_ids=["QINGLAN-50", "QINGLAN-100"])
    run = create_run(["CASE-1"], root=isolated_root, execution_mode="stub")
    result = generate(request, run, "CASE-1", root=isolated_root, model_call=lambda *args: de_ai_stub(raw_texts), execution_mode="stub")
    assert result.status == "success"
    assert result.candidates[0].text == "关于您提到的预算问题，青岚50毫升是980元"
    assert result.candidates[1].text == raw_texts[1]
    assert result.candidates[2].text == raw_texts[2]
    report = result.de_ai_report
    assert report["gate"] == "applied"
    p0, p1, p2 = report["per_candidate"]
    assert p0["candidate_id"].endswith("-C1") and p0["cleaned"] is True
    assert p0["applied_rules"] == ["万能结尾", "客服开场"]
    assert {"万能结尾", "客服开场", "总起句"} <= categories(p0["lint_hits"])
    assert p1["cleaned"] is False and p1["lint_hits"] == []
    assert p2["cleaned"] is False and p2["skipped_reason"] == "清洗后为空"
    assert result.provenance["de_ai_gate"] == "applied"
    assert result.warnings == []
    case_dir = isolated_root / "artifacts" / "runs" / run / "cases" / "CASE-1"
    attempt = json.loads((case_dir / "attempts.jsonl").read_text(encoding="utf-8"))
    assert attempt["raw_text"] == de_ai_stub(raw_texts)["raw_text"]
    saved = json.loads((case_dir / "result.json").read_text(encoding="utf-8"))
    assert saved["candidates"][0]["text"] == "关于您提到的预算问题，青岚50毫升是980元"
    assert saved["de_ai_report"]["gate"] == "applied"


def test_generate_skips_cleaning_on_duplicate(isolated_root: Path):
    raw_texts = ["祝您生活愉快！价格980元。", "价格980元。", "青岚100毫升是1580元。"]
    request = GenerationRequest(scenario="产品推荐", client_information={"current_need": "想了解青岚"}, product_ids=["QINGLAN-50", "QINGLAN-100"])
    run = create_run(["CASE-1"], root=isolated_root, execution_mode="stub")
    result = generate(request, run, "CASE-1", root=isolated_root, model_call=lambda *args: de_ai_stub(raw_texts), execution_mode="stub")
    assert result.status == "success"
    assert result.candidates[0].text == raw_texts[0]
    p0 = result.de_ai_report["per_candidate"][0]
    assert p0["cleaned"] is False and p0["skipped_reason"] == "清洗后与其他候选重复"
    assert {candidate.text for candidate in result.candidates} == set(raw_texts)


def test_non_success_result_has_empty_de_ai_report():
    result = GenerationResult(run_id="r", case_id="c", status="needs_input")
    assert result.de_ai_report == {}


# ---------- 上下文重复检测 ----------

def test_lint_context_duplication_hit():
    history = [{"role": "client", "content": "我想给妹妹挑一款柑橘调的香水，预算一千以内。"}]
    hits = lint_text("我想给妹妹挑一款柑橘调的香水，这款很合适。", conversation_history=history)
    assert "上下文重复" in categories(hits)
    hit = next(hit for hit in hits if hit["category"] == "上下文重复")
    assert "我想给妹妹挑一款柑橘调的香水" in hit["match"]
    assert "来源" in hit["message"] and "client" in hit["message"]


def test_lint_context_duplication_below_threshold_no_hit():
    history = [{"role": "client", "content": "挑一款柑橘调的香水，预算一千以内。"}]
    # 「挑一款柑橘调的香水」只有 9 个连续 CJK 字符，未到 10 字阈值。
    assert "上下文重复" not in categories(lint_text("挑一款柑橘调的香水", conversation_history=history))


def test_lint_context_duplication_ignores_punctuation_and_space():
    history = [{"role": "client", "content": "我想，给妹妹 挑一款柑橘调的香水。"}]
    hits = lint_text("我想给妹妹挑一款柑橘调的香水", conversation_history=history)
    assert "上下文重复" in categories(hits)


def test_lint_context_duplication_advisor_message_not_source():
    history = [
        {"role": "advisor", "content": "您平时喜欢哪一种气味呢？"},
        {"role": "client", "content": "我预算一千以内。"},
    ]
    assert "上下文重复" not in categories(lint_text("您平时喜欢哪一种气味呢", conversation_history=history))


def test_lint_context_duplication_no_history_no_hit():
    assert "上下文重复" not in categories(lint_text("我想给妹妹挑一款柑橘调的香水。"))


# ---------- 场景适配检测 ----------

def test_lint_birthday_scenario_product_name_alone_no_hit():
    # 新规则允许基于事实的个性化提及（如「您上次选了青岚」），裸商品名不再命中。
    assert "场景不适配" not in categories(lint_text("祝您生日快乐，您上次选了青岚。", scenario="生日与节庆"))


def test_lint_birthday_scenario_promo_words_hit():
    hits = lint_text("祝您生日快乐，本周有优惠活动，欢迎到店。", scenario="生日与节庆")
    promo = {hit["match"] for hit in hits if hit["category"] == "场景不适配"}
    assert promo >= {"优惠", "活动", "到店"}


def test_lint_birthday_scenario_trial_visit_hit():
    hits = lint_text("祝您生日快乐，欢迎到店试闻新款。", scenario="生日与节庆")
    promo = {hit["match"] for hit in hits if hit["category"] == "场景不适配"}
    assert promo >= {"到店", "试闻"}


def test_lint_birthday_scenario_new_promo_words_hit():
    hits = lint_text("祝您生日快乐，全场有折扣，推荐您比较一下，可以登记意向。", scenario="生日与节庆")
    promo = {hit["match"] for hit in hits if hit["category"] == "场景不适配"}
    assert promo >= {"折扣", "推荐", "比较", "登记"}


def test_lint_other_scenario_no_birthday_hit():
    text = "青岚50毫升是980元，可以到店试闻。"
    assert "场景不适配" not in categories(lint_text(text, scenario="产品推荐"))
    assert "场景不适配" not in categories(lint_text(text))


def test_lint_birthday_blessing_without_product_no_hit():
    assert "场景不适配" not in categories(lint_text("祝您生日快乐，愿新的一岁顺心如意。", scenario="生日与节庆"))


def test_generate_reports_new_hits_without_modifying_text(isolated_root: Path):
    history = [{"role": "client", "content": "今天是我生日，想收到一份祝福。"}]
    raw_texts = [
        "今天是我生日，想收到一份祝福。祝您生日快乐！",
        "青岚50毫升是980元，您可以到店试闻。",
        "祝您生日快乐，愿新的一岁顺心如意。",
    ]
    request = GenerationRequest(scenario="生日与节庆", occasion="生日",
        client_information={"buyer": {"address": "林女士"}, "current_need": "生日祝福"},
        conversation_history=history)
    run = create_run(["CASE-1"], root=isolated_root, execution_mode="stub")
    result = generate(request, run, "CASE-1", root=isolated_root, model_call=lambda *args: de_ai_stub(raw_texts), execution_mode="stub")
    assert result.status == "success"
    p0, p1, p2 = result.de_ai_report["per_candidate"]
    assert "上下文重复" in categories(p0["lint_hits"])
    assert "场景不适配" in categories(p1["lint_hits"])
    assert p2["lint_hits"] == []
    # 新两类仅报告，不自动修改文本。
    assert result.candidates[0].text == raw_texts[0]
    assert result.candidates[1].text == raw_texts[1]
    assert result.candidates[2].text == raw_texts[2]
