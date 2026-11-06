"""Streamlit 与批量 CLI 共用的一次生成流程。"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .data import PROJECT_ROOT, contact_is_blocked, load_facts, required_information
from .model import ModelCallError, ModelConfig, call_model, get_config, public_config
from .models import Candidate, GenerationRequest, GenerationResult, valid_id
from .records import append_jsonl, begin_case, save_result, source_versions, timestamp


class _Draft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=3000)


class _Drafts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidates: list[_Draft] = Field(min_length=3, max_length=3)


def build_messages(request: GenerationRequest, facts: dict[str, Any], *, root: Path = PROJECT_ROOT) -> list[dict[str, str]]:
    prompt_dir = Path(root) / "src" / "qixu_advisor" / "prompts"
    system = (prompt_dir / "system.txt").read_text(encoding="utf-8")
    scenes = json.loads((prompt_dir / "scenarios.json").read_text(encoding="utf-8"))
    return [
        {"role": "system", "content": system + "\n本场景要求：" + scenes[request.scenario]},
        {"role": "user", "content": json.dumps({"request": request.model_dump(mode="json"), "facts": facts}, ensure_ascii=False)},
    ]


def check_explicit_facts(candidates: list[Candidate], facts: dict[str, Any]) -> list[str]:
    """只提示能定位的商品容量/金额矛盾；绝不把规则通过等同于内容合格。"""
    products = facts.get("products", [])
    names = sorted({item.get("name", "") for item in products if item.get("name")}, key=len, reverse=True)
    if not names:
        return []
    names_pattern = "|".join(re.escape(name) for name in names)
    pair_pattern = re.compile(r"(\d+(?:\.\d+)?)\s*(?:mL|ml|ML|毫升)[^。；;\n]{0,30}?(\d[\d,]*(?:\.\d+)?)\s*元")
    warnings = []
    for candidate in candidates:
        mentions = list(re.finditer(names_pattern, candidate.text))
        for index, mention in enumerate(mentions):
            end = mentions[index + 1].start() if index + 1 < len(mentions) else len(candidate.text)
            fragment = candidate.text[mention.end():end]
            name = mention.group()
            variants = [item for item in products if item.get("name") == name]
            for pair in pair_pattern.finditer(fragment):
                volume, price = float(pair[1]), float(pair[2].replace(",", ""))
                matching = [item for item in variants if float(item.get("volume_ml", -1)) == volume]
                if not matching:
                    warnings.append(f"{candidate.candidate_id}：{name} {volume:g} mL 未在本次商品资料中找到，请核对规格。")
                elif not any(float(item.get("price_cny", -1)) == price for item in matching):
                    expected = " / ".join(f"{item['price_cny']} 元" for item in matching)
                    warnings.append(f"{candidate.candidate_id}：{name} {volume:g} mL 附近出现 {price:g} 元，资料价格为 {expected}；请核对是品牌报价还是顾客原话。")
    return list(dict.fromkeys(warnings))


def generate(request: GenerationRequest | dict[str, Any], run_id: str, case_id: str, *, root: Path = PROJECT_ROOT, model_call: Callable[[list[dict[str, str]], ModelConfig], dict[str, Any]] | None = None, execution_mode: str = "real") -> GenerationResult:
    """一次请求只调用一次模型，先保存输入和原始返回，再检验结构。"""
    valid_id(run_id)
    valid_id(case_id)
    request = GenerationRequest.model_validate(request)
    if model_call is not None and execution_mode != "stub":
        raise ValueError("注入测试替身必须显式标记 execution_mode='stub'")
    if execution_mode == "stub" and model_call is None:
        raise ValueError("stub 模式须提供替身，不能调用真实模型")
    start = time.perf_counter()
    facts: dict[str, Any] = {}
    messages: list[dict[str, str]] = []
    setup_error = None
    try:
        facts = load_facts(request, root=root)
        messages = build_messages(request, facts, root=root)
        config = get_config(root)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        setup_error = f"本地资料、提示或配置读取失败（{type(exc).__name__}），请检查文件与参数"
        config = ModelConfig()
    provenance = {"execution_mode": execution_mode, "created_at": timestamp(), "versions": source_versions(root), "model_config": public_config(config), "model_call_count": 0, "quality_status": "not_human_evaluated"}
    path = begin_case(run_id, case_id, {"schema_version": "1.0", "run_id": run_id, "case_id": case_id, "created_at": timestamp(), "request": request.model_dump(mode="json"), "facts": facts, "messages": messages, "provenance": provenance}, root=root, execution_mode=execution_mode)

    def finish(status: str, **fields: Any) -> GenerationResult:
        result = GenerationResult(run_id=run_id, case_id=case_id, status=status, fact_references=facts.get("references", []), provenance={**provenance, "elapsed_seconds": time.perf_counter() - start}, **fields)
        # 保存失败直接抛出，调用端不得把未保存的结果展示成完整成功。
        save_result(result, root=root)
        return result

    if setup_error:
        return finish("technical_failure", error=setup_error)
    if contact_is_blocked(request, facts):
        return finish("contact_blocked", error="资料明确禁止联系，本次未调用模型")
    missing = required_information(request, facts)
    if missing:
        return finish("needs_input", missing_fields=missing)
    if execution_mode == "real" and not config.api_key.get_secret_value().strip():
        return finish("technical_failure", error="未配置 DEEPSEEK_API_KEY；未发起真实模型请求")

    attempt = {"attempt": 1, "started_at": timestamp(), "execution_mode": execution_mode, "model_config": public_config(config)}
    caller = model_call or call_model
    try:
        response = caller(messages, config)
        provenance["model_call_count"] = 1
        attempt.update(response)
        attempt["status"] = "received"
    except ModelCallError as exc:
        provenance["model_call_count"] = int(exc.details.get("attempted", True))
        attempt.update({"status": "error", "error": str(exc), **exc.details})
        append_jsonl(path / "attempts.jsonl", attempt)
        return finish("technical_failure", error=str(exc))
    except Exception as exc:
        # 非预期适配器错误不记录异常文本，防止其中包含环境凭据。
        provenance["model_call_count"] = 1
        error = f"模型调用发生 {type(exc).__name__}；未自动重试"
        attempt.update({"status": "error", "error": error})
        append_jsonl(path / "attempts.jsonl", attempt)
        return finish("technical_failure", error=error)
    # 原始响应在解析之前落盘；结构不合格也能回溯首轮返回。
    append_jsonl(path / "attempts.jsonl", attempt)
    provenance.update({"returned_model": response.get("model"), "usage": response.get("usage", {}), "model_elapsed_seconds": response.get("elapsed_seconds")})
    try:
        if response.get("finish_reason") not in {None, "stop"}:
            raise ValueError("输出未正常结束")
        drafts = _Drafts.model_validate_json(response["raw_text"])
        candidates = [Candidate(candidate_id=f"{case_id}-C{index}", text=draft.text) for index, draft in enumerate(drafts.candidates, 1)]
        if len({candidate.text for candidate in candidates}) != 3:
            raise ValueError("三条候选完全重复")
    except (ValidationError, ValueError, KeyError, TypeError):
        return finish("technical_failure", error="模型输出结构不合格：需要三条不同、非空的中文完整候选；原始返回已保存，未重抽")
    return finish("success", candidates=candidates, warnings=check_explicit_facts(candidates, facts))
