"""对话分析函数（analyze_conversation）的离线检查；模型一律显式替身，零真实 API 调用。"""

import json
from pathlib import Path

import pytest

from qixu_advisor.generation import analyze_conversation
from qixu_advisor.model import ModelCallError
from qixu_advisor.models import AnalysisResult


ANALYSIS_PROMPT = "你是对话分析助手。仅返回 JSON：{\"scenario\":\"六场景之一\",\"current_need\":\"本次需求摘要\",\"missing_questions\":[\"待确认问题\"]}"


@pytest.fixture
def analysis_root(tmp_path: Path) -> Path:
    """临时 root fixture：自建 prompts/analysis.txt，不依赖仓库内提示文件。"""
    prompt_dir = tmp_path / "src" / "qixu_advisor" / "prompts"
    prompt_dir.mkdir(parents=True)
    (prompt_dir / "analysis.txt").write_text(ANALYSIS_PROMPT, encoding="utf-8")
    return tmp_path


def analysis_stub(payload) -> dict:
    raw = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return {"raw_text": raw, "model": "offline-analysis-stub", "usage": {}, "elapsed_seconds": 0, "finish_reason": "stop"}


def valid_payload() -> dict:
    return {"scenario": "价格异议", "current_need": "客户觉得雨白 50 mL 偏贵，想了解是否有优惠", "missing_questions": ["您的预算范围大概是多少？", "是否到店试闻过？"]}


def test_valid_analysis_passes_and_assembles_messages(analysis_root: Path):
    calls = []

    def stub(messages, config):
        calls.append(messages)
        return analysis_stub(valid_payload())

    history = [{"role": "client", "content": "1180元有点贵，我还没确定是不是喜欢。"}]
    info = {"buyer": {"address": "许女士"}, "budget_cny": 1000}
    result = analyze_conversation(history, info, root=analysis_root, model_call=stub, execution_mode="stub")
    assert isinstance(result, AnalysisResult)
    assert result.scenario == "价格异议"
    assert result.current_need == valid_payload()["current_need"]
    assert result.missing_questions == valid_payload()["missing_questions"]
    assert len(calls) == 1
    messages = calls[0]
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == ANALYSIS_PROMPT
    payload = json.loads(messages[1]["content"])
    assert payload == {"conversation_history": history, "client_information": info}


def test_client_information_none_becomes_empty_object(analysis_root: Path):
    def stub(messages, config):
        return analysis_stub({"scenario": "生日与节庆", "current_need": "客户今天生日"})

    result = analyze_conversation([{"role": "client", "content": "今天是我生日。"}], None, root=analysis_root, model_call=stub, execution_mode="stub")
    assert result.scenario == "生日与节庆"
    assert result.missing_questions == []


def test_invalid_json_raises_without_retry(analysis_root: Path):
    calls = []

    def stub(messages, config):
        calls.append(messages)
        return analysis_stub("原始非 JSON 输出")

    with pytest.raises(ValueError, match="结构不合格") as caught:
        analyze_conversation([], {}, root=analysis_root, model_call=stub, execution_mode="stub")
    assert "未重试" in str(caught.value)
    assert len(calls) == 1


def test_missing_fields_raise(analysis_root: Path):
    def stub(messages, config):
        return analysis_stub({"scenario": "价格异议"})

    with pytest.raises(ValueError, match="结构不合格"):
        analyze_conversation([], {}, root=analysis_root, model_call=stub, execution_mode="stub")


def test_invalid_scenario_raises(analysis_root: Path):
    def stub(messages, config):
        return analysis_stub({"scenario": "闲聊", "current_need": "随便聊聊"})

    with pytest.raises(ValueError, match="结构不合格"):
        analyze_conversation([], {}, root=analysis_root, model_call=stub, execution_mode="stub")


def test_more_than_three_questions_raise(analysis_root: Path):
    def stub(messages, config):
        return analysis_stub({"scenario": "产品推荐", "current_need": "送朋友", "missing_questions": ["q1", "q2", "q3", "q4"]})

    with pytest.raises(ValueError, match="结构不合格"):
        analyze_conversation([], {}, root=analysis_root, model_call=stub, execution_mode="stub")


def test_empty_question_raises(analysis_root: Path):
    def stub(messages, config):
        return analysis_stub({"scenario": "产品推荐", "current_need": "送朋友", "missing_questions": [""]})

    with pytest.raises(ValueError, match="结构不合格"):
        analyze_conversation([], {}, root=analysis_root, model_call=stub, execution_mode="stub")


def test_empty_current_need_raises(analysis_root: Path):
    def stub(messages, config):
        return analysis_stub({"scenario": "产品推荐", "current_need": "   "})

    with pytest.raises(ValueError, match="结构不合格"):
        analyze_conversation([], {}, root=analysis_root, model_call=stub, execution_mode="stub")


def test_stub_without_explicit_mode_is_rejected(analysis_root: Path):
    with pytest.raises(ValueError, match="stub"):
        analyze_conversation([], {}, root=analysis_root, model_call=lambda *args: analysis_stub(valid_payload()))


def test_stub_mode_without_model_call_is_rejected(analysis_root: Path):
    with pytest.raises(ValueError, match="替身"):
        analyze_conversation([], {}, root=analysis_root, execution_mode="stub")


def test_missing_analysis_prompt_raises_explicitly(tmp_path: Path):
    with pytest.raises(ValueError, match="analysis.txt"):
        analyze_conversation([], {}, root=tmp_path, model_call=lambda *args: analysis_stub(valid_payload()), execution_mode="stub")


def test_model_call_error_converted_without_retry(analysis_root: Path):
    calls = []

    def stub(messages, config):
        calls.append(messages)
        raise ModelCallError("模型接口返回 HTTP 402：账户余额不足；没有自动重试", details={"attempted": True})

    with pytest.raises(ValueError, match="未自动重试") as caught:
        analyze_conversation([], {}, root=analysis_root, model_call=stub, execution_mode="stub")
    assert "账户余额不足" in str(caught.value)
    assert len(calls) == 1


def test_unexpected_adapter_error_hides_exception_text(analysis_root: Path):
    def stub(messages, config):
        raise RuntimeError("secret-token-must-not-leak")

    with pytest.raises(ValueError, match="未自动重试") as caught:
        analyze_conversation([], {}, root=analysis_root, model_call=stub, execution_mode="stub")
    assert "secret-token-must-not-leak" not in str(caught.value)
    assert "RuntimeError" in str(caught.value)


def test_real_mode_without_key_raises(analysis_root: Path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(ValueError, match="未配置 DEEPSEEK_API_KEY"):
        analyze_conversation([], {}, root=analysis_root)
