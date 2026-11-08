"""运行时模型配置与运行留档的衔接检查：create_run(config=...) 记录实际配置，begin_case 守卫一致放行/拦截。"""

import json
import shutil
from pathlib import Path

import pytest
from pydantic import SecretStr

from qixu_advisor.data import PROJECT_ROOT
from qixu_advisor.generation import generate
from qixu_advisor.model import ModelConfig, public_config
from qixu_advisor.models import GenerationRequest
from qixu_advisor.records import create_run


@pytest.fixture
def isolated_root(tmp_path: Path) -> Path:
    shutil.copytree(PROJECT_ROOT / "data" / "fictional", tmp_path / "data" / "fictional")
    shutil.copytree(PROJECT_ROOT / "src" / "qixu_advisor", tmp_path / "src" / "qixu_advisor", ignore=shutil.ignore_patterns("__pycache__"))
    return tmp_path


def stub_response() -> dict:
    return {"raw_text": json.dumps({"candidates": [{"text": "测试替身第一条：这只用于检查程序结构。"}, {"text": "测试替身第二条：这些文字不是模型实测。"}, {"text": "测试替身第三条：不要将其作为正式业务输出。"}]}, ensure_ascii=False), "model": "offline-test-stub", "usage": {}, "elapsed_seconds": 0, "finish_reason": "stop"}


def runtime_config() -> ModelConfig:
    return ModelConfig(provider="deepseek", model="runtime-model", base_url="https://runtime.example.com", api_key=SecretStr("runtime-secret"))


def test_create_run_manifest_records_runtime_config_without_secret(isolated_root: Path):
    run = create_run(["CASE-1"], root=isolated_root, execution_mode="stub", config=runtime_config())
    manifest = json.loads((isolated_root / "artifacts" / "runs" / run / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["model_config"] == public_config(runtime_config())
    assert manifest["model_config"]["model"] == "runtime-model"
    assert manifest["model_config"]["base_url"] == "https://runtime.example.com"
    assert "runtime-secret" not in json.dumps(manifest, ensure_ascii=False)
    assert "api_key" not in manifest["model_config"]


def test_runtime_config_run_generation_passes_guards(isolated_root: Path):
    config = runtime_config()
    run = create_run(["CASE-1"], root=isolated_root, execution_mode="stub", config=config)
    result = generate(GenerationRequest(scenario="生日与节庆", occasion="生日"), run, "CASE-1", root=isolated_root,
        model_call=lambda *args: stub_response(), execution_mode="stub", config=config)
    assert result.status == "success"
    assert result.provenance["model_config"]["model"] == "runtime-model"


def test_default_run_rejects_mismatched_config(isolated_root: Path):
    """对照组：manifest 记录默认配置时，generate 使用不同配置仍被守卫拦截。"""
    run = create_run(["CASE-1"], root=isolated_root, execution_mode="stub")
    different = ModelConfig(model="different-model", api_key=SecretStr("x"))
    with pytest.raises(ValueError, match="模型参数"):
        generate(GenerationRequest(scenario="生日与节庆", occasion="生日"), run, "CASE-1", root=isolated_root,
            model_call=lambda *args: stub_response(), execution_mode="stub", config=different)
