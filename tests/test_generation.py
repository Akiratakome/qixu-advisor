"""离线程序检查：所有文案均为显式替身，不证明模型内容质量。"""

import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
from pydantic import SecretStr

from qixu_advisor.data import PROJECT_ROOT, load_facts
from qixu_advisor.generation import check_explicit_facts, generate
from qixu_advisor.model import ModelCallError, ModelConfig, call_model
from qixu_advisor.models import Candidate, GenerationRequest, SCENARIOS
from qixu_advisor.records import create_run, save_feedback


@pytest.fixture
def isolated_root(tmp_path: Path) -> Path:
    shutil.copytree(PROJECT_ROOT / "data" / "fictional", tmp_path / "data" / "fictional")
    shutil.copytree(PROJECT_ROOT / "src" / "qixu_advisor", tmp_path / "src" / "qixu_advisor", ignore=shutil.ignore_patterns("__pycache__"))
    return tmp_path


def stub_response() -> dict:
    return {"raw_text": json.dumps({"candidates": [{"text": "测试替身第一条：这只用于检查程序结构。"}, {"text": "测试替身第二条：这些文字不是模型实测。"}, {"text": "测试替身第三条：不要将其作为正式业务输出。"}]}, ensure_ascii=False), "model": "offline-test-stub", "usage": {}, "elapsed_seconds": 0, "finish_reason": "stop"}


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_six_scenarios_use_shared_core(isolated_root: Path, scenario: str):
    request = GenerationRequest(scenario=scenario, client_information={"current_need": "希望了解现有资料", "relationship": "曾到店试香"}, occasion="生日", event_id="EVT-CITRUS")
    caller = MagicMock(return_value=stub_response())
    run = create_run(["CASE-1"], root=isolated_root, execution_mode="stub")
    result = generate(request, run, "CASE-1", root=isolated_root, model_call=caller, execution_mode="stub")
    assert result.status == "success"
    assert len(result.candidates) == 3
    assert len({candidate.candidate_id for candidate in result.candidates}) == 3
    assert result.provenance["execution_mode"] == "stub"
    assert result.provenance["model_call_count"] == 1
    assert caller.call_count == 1
    case_dir = isolated_root / "artifacts" / "runs" / run / "cases" / "CASE-1"
    attempt = json.loads((case_dir / "attempts.jsonl").read_text(encoding="utf-8"))
    assert attempt["raw_text"] == stub_response()["raw_text"]


@pytest.mark.parametrize("generation_request,status", [
    (GenerationRequest(scenario="生日与节庆", occasion="生日", client_information={"contact_permission": "blocked"}), "contact_blocked"),
    (GenerationRequest(scenario="活动邀请"), "needs_input"),
    (GenerationRequest(scenario="沉睡唤醒", client_information={"buyer": "", "current_need": "", "contact_permission": "unknown"}), "needs_input"),
])
def test_preflight_does_not_call_model(isolated_root: Path, generation_request: GenerationRequest, status: str):
    caller = MagicMock(side_effect=AssertionError("preflight must not call model"))
    run = create_run(["CASE-1"], root=isolated_root, execution_mode="stub")
    result = generate(generation_request, run, "CASE-1", root=isolated_root, model_call=caller, execution_mode="stub")
    assert result.status == status
    assert result.candidates == []
    caller.assert_not_called()


def test_invalid_raw_output_is_retained_without_retry(isolated_root: Path):
    caller = MagicMock(return_value={"raw_text": "原始非 JSON 输出", "model": "offline-test-stub"})
    run = create_run(["CASE-1"], root=isolated_root, execution_mode="stub")
    result = generate(GenerationRequest(scenario="生日与节庆", occasion="生日"), run, "CASE-1", root=isolated_root, model_call=caller, execution_mode="stub")
    assert result.status == "technical_failure"
    assert result.candidates == []
    assert caller.call_count == 1
    path = isolated_root / "artifacts" / "runs" / run / "cases" / "CASE-1"
    assert json.loads((path / "attempts.jsonl").read_text(encoding="utf-8"))["raw_text"] == "原始非 JSON 输出"


def test_sku_amount_and_machine_edit_separation(isolated_root: Path):
    request = GenerationRequest(scenario="产品推荐", client_id="C001", client_information={"current_need": "给妹妹选柑橘香"}, product_ids=["QINGLAN"])
    facts = load_facts(request, root=isolated_root)
    assert facts["customer_profile"]["client_id"] == "C001"
    assert {product["volume_ml"] for product in facts["products"]} == {50, 100}
    assert all(product["stock"] is None for product in facts["products"])
    wrong = Candidate(candidate_id="wrong", text="青岚50 mL是1580元，可以先试香。")
    right = Candidate(candidate_id="right", text="青岚50 mL是980元，可以先试香。")
    assert len(check_explicit_facts([wrong], facts)) == 1
    assert check_explicit_facts([right], facts) == []
    run = create_run(["CASE-1"], root=isolated_root, execution_mode="stub")
    result = generate(request, run, "CASE-1", root=isolated_root, model_call=lambda *args: stub_response(), execution_mode="stub")
    path = isolated_root / "artifacts" / "runs" / run / "cases" / "CASE-1"
    originals = {name: (path / name).read_bytes() for name in ["input.json", "attempts.jsonl", "result.json"]}
    feedback = save_feedback(run, "CASE-1", result.candidates[0].candidate_id, "edit", "这是人工编辑的离线检查稿。", "测试操作人", root=isolated_root)
    assert feedback["sent"] is False
    assert all((path / name).read_bytes() == content for name, content in originals.items())
    with pytest.raises(FileExistsError):
        generate(request, run, "CASE-1", root=isolated_root, model_call=lambda *args: stub_response(), execution_mode="stub")


def test_evaluation_expectations_never_enter_prompt(isolated_root: Path):
    cases_dir = isolated_root / "data" / "cases"
    cases_dir.mkdir()
    (cases_dir / "expectations.jsonl").write_text('{"secret_label":"NEVER_IN_PROMPT"}\n', encoding="utf-8")
    caller = MagicMock(return_value=stub_response())
    run = create_run(["CASE-1"], root=isolated_root, execution_mode="stub")
    generate(GenerationRequest(scenario="生日与节庆", occasion="生日"), run, "CASE-1", root=isolated_root, model_call=caller, execution_mode="stub")
    prompt = json.dumps(caller.call_args.args[0], ensure_ascii=False)
    assert "NEVER_IN_PROMPT" not in prompt
    assert "secret_label" not in prompt


def test_observed_402_has_actionable_message_and_no_retry():
    """真实运行已遇到402；这里仅验证修复后的错误呈现，没有真实API调用。"""
    response = httpx.Response(402, json={"error": {"message": "Insufficient Balance"}})
    client = MagicMock()
    client.__enter__.return_value = client
    client.post.return_value = response
    with patch("qixu_advisor.model.httpx.Client", return_value=client):
        with pytest.raises(ModelCallError, match="账户余额不足") as caught:
            call_model([{"role": "user", "content": "离线检查"}], ModelConfig(api_key=SecretStr("test-only-secret")))
    assert caught.value.details["http_status"] == 402
    assert "test-only-secret" not in str(caught.value)
    assert client.post.call_count == 1


def test_runtime_config_override_priority(isolated_root: Path, monkeypatch):
    """运行时设置（界面自配）逐键优先于 .env；空字符串视为未设置回退。"""
    from qixu_advisor.model import config_status, get_config

    (isolated_root / ".env").write_text("QIXU_MODEL=env-model\nQIXU_BASE_URL=https://env.example.com\n", encoding="utf-8")
    monkeypatch.delenv("QIXU_MODEL", raising=False)
    monkeypatch.delenv("QIXU_BASE_URL", raising=False)
    config = get_config(isolated_root, runtime={"model": "runtime-model", "base_url": "https://runtime.example.com/", "api_key": "runtime-key"})
    assert config.model == "runtime-model"
    assert config.base_url == "https://runtime.example.com"
    assert config.api_key.get_secret_value() == "runtime-key"
    # 空字符串回退到 .env。
    fallback = get_config(isolated_root, runtime={"model": "", "base_url": ""})
    assert fallback.model == "env-model"
    assert fallback.base_url == "https://env.example.com"
    status = config_status(isolated_root, runtime={"api_key": "runtime-key"})
    assert status["configured"] is True and status["model"] == "env-model"


def test_generate_uses_explicit_config_and_skips_env(isolated_root: Path, monkeypatch):
    """config 显式传入时跳过内部 get_config：无效 .env 不阻碍生成；替身收到运行时配置。"""
    from qixu_advisor import records as records_module

    (isolated_root / ".env").write_text("QIXU_TEMPERATURE=not-a-float\n", encoding="utf-8")
    supplied = ModelConfig(provider="deepseek", model="runtime-model", base_url="https://runtime.example.com", api_key=SecretStr("runtime-key"))
    # 运行清单（records.create_run）须记录同一实际配置，否则 begin_case 的"运行内参数不变"守卫会拦截；
    # records.py 不在本次改动用域，测试中把 records 引用的 get_config 对齐为实际配置。
    monkeypatch.setattr(records_module, "get_config", lambda root: supplied)
    received = []

    def stub(messages, config):
        received.append(config)
        return stub_response()

    run = create_run(["CASE-1"], root=isolated_root, execution_mode="stub")
    result = generate(GenerationRequest(scenario="生日与节庆", occasion="生日"), run, "CASE-1", root=isolated_root,
        model_call=stub, execution_mode="stub", config=supplied)
    assert result.status == "success"
    assert len(received) == 1
    assert received[0].model == "runtime-model"
    assert received[0].base_url == "https://runtime.example.com"
    assert result.provenance["model_config"]["model"] == "runtime-model"
    assert result.provenance["model_config"]["base_url"] == "https://runtime.example.com"


def test_generate_invalid_env_without_explicit_config_fails(isolated_root: Path, monkeypatch):
    """对照组：不传 config 时无效 .env 触发显式配置失败，不进模型调用。"""
    from qixu_advisor import records as records_module

    (isolated_root / ".env").write_text("QIXU_TEMPERATURE=not-a-float\n", encoding="utf-8")
    # 失败路径的兜底配置是 ModelConfig()，让 manifest 快照与之一致，守卫不掩盖真正的配置失败。
    monkeypatch.setattr(records_module, "get_config", lambda root: ModelConfig())
    caller = MagicMock(side_effect=AssertionError("must not call model"))
    run = create_run(["CASE-1"], root=isolated_root, execution_mode="stub")
    result = generate(GenerationRequest(scenario="生日与节庆", occasion="生日"), run, "CASE-1", root=isolated_root,
        model_call=caller, execution_mode="stub")
    assert result.status == "technical_failure"
    assert "配置" in result.error
    caller.assert_not_called()


def test_analyze_conversation_uses_explicit_config(isolated_root: Path):
    from qixu_advisor.generation import analyze_conversation

    prompt_dir = isolated_root / "src" / "qixu_advisor" / "prompts"
    if not (prompt_dir / "analysis.txt").exists():
        (prompt_dir / "analysis.txt").write_text("你是对话分析助手。仅返回 JSON。", encoding="utf-8")
    supplied = ModelConfig(provider="deepseek", model="runtime-analysis-model", base_url="https://runtime.example.com", api_key=SecretStr("runtime-key"))
    received = []

    def stub(messages, config):
        received.append(config)
        return {"raw_text": json.dumps({"scenario": "价格异议", "current_need": "觉得贵"}, ensure_ascii=False), "model": "offline-analysis-stub", "usage": {}, "elapsed_seconds": 0, "finish_reason": "stop"}

    result = analyze_conversation([{"role": "client", "content": "有点贵。"}], {}, root=isolated_root, model_call=stub, execution_mode="stub", config=supplied)
    assert result.scenario == "价格异议"
    assert len(received) == 1
    assert received[0].model == "runtime-analysis-model"
