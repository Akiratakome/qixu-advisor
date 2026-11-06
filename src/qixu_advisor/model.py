"""当前仅连接 DeepSeek；不进行自动重试，不用示例替代真实返回。"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import httpx
from dotenv import dotenv_values
from pydantic import BaseModel, Field, SecretStr

from .data import PROJECT_ROOT


class ModelConfig(BaseModel):
    provider: str = "deepseek"
    model: str = "deepseek-flash"
    base_url: str = "https://api.deepseek.com"
    api_key: SecretStr = Field(default=SecretStr(""), exclude=True)
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=1800, ge=256, le=8192)
    timeout_seconds: float = Field(default=90, ge=1, le=300)
    thinking: dict[str, str] = Field(default_factory=lambda: {"type": "disabled"})
    response_format: dict[str, str] = Field(default_factory=lambda: {"type": "json_object"})


class ModelCallError(RuntimeError):
    """只携带已清洗的错误与可安全落盘的响应信息。"""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.details = details or {}


def get_config(root: Path = PROJECT_ROOT) -> ModelConfig:
    local = dotenv_values(Path(root) / ".env")

    def value(name: str, default: str) -> str:
        return os.environ.get(name) or local.get(name) or default

    return ModelConfig(
        api_key=SecretStr(value("DEEPSEEK_API_KEY", "")),
        model=value("QIXU_MODEL", "deepseek-flash"),
        base_url=value("QIXU_BASE_URL", "https://api.deepseek.com").rstrip("/"),
        temperature=float(value("QIXU_TEMPERATURE", "0.7")),
        max_tokens=int(value("QIXU_MAX_TOKENS", "1800")),
        timeout_seconds=float(value("QIXU_TIMEOUT_SECONDS", "90")),
    )


def public_config(config: ModelConfig) -> dict[str, Any]:
    # SecretStr 标记只是辅助；明确 exclude，禁止凭据进入 manifest。
    return config.model_dump(exclude={"api_key"})


def config_status(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    try:
        config = get_config(root)
    except (ValueError, TypeError):
        return {"configured": False, "provider": "deepseek", "model": None, "base_url": None, "missing": ["模型参数格式无效，请检查 .env"]}
    missing = [] if config.api_key.get_secret_value().strip() else ["DEEPSEEK_API_KEY"]
    return {"configured": not missing, "provider": config.provider, "model": config.model, "base_url": config.base_url, "missing": missing}


def call_model(messages: list[dict[str, str]], config: ModelConfig) -> dict[str, Any]:
    key = config.api_key.get_secret_value().strip()
    if not key:
        raise ModelCallError("未配置 DEEPSEEK_API_KEY；未发起真实模型请求", details={"attempted": False})
    payload = {"model": config.model, "messages": messages, "temperature": config.temperature, "max_tokens": config.max_tokens, "thinking": config.thinking, "response_format": config.response_format, "stream": False}
    start = time.perf_counter()
    try:
        # httpx 无隐式请求重试；不用 SDK 的默认重试掩盖第一次失败。
        with httpx.Client(timeout=config.timeout_seconds, follow_redirects=False) as client:
            response = client.post(config.base_url + "/chat/completions", headers={"Authorization": f"Bearer {key}"}, json=payload)
    except httpx.TimeoutException as exc:
        raise ModelCallError("模型请求超时；没有自动重试", details={"attempted": True, "elapsed_seconds": time.perf_counter() - start, "error_type": "timeout"}) from exc
    except httpx.RequestError as exc:
        raise ModelCallError("模型连接失败；没有自动重试", details={"attempted": True, "elapsed_seconds": time.perf_counter() - start, "error_type": "connection"}) from exc
    elapsed = time.perf_counter() - start
    if response.status_code != 200:
        # 不落盘 HTTP headers 或任意错误 body，防止服务端回显凭据。
        explanation = {401: "凭据无效，请检查本地密钥", 402: "账户余额不足，请在 DeepSeek 平台补充余额后再创建新运行", 429: "请求频率受限，请稍后再创建新运行", 500: "模型服务内部错误", 503: "模型服务繁忙"}.get(response.status_code, "请检查接口配置和服务状态")
        raise ModelCallError(f"模型接口返回 HTTP {response.status_code}：{explanation}；没有自动重试", details={"attempted": True, "elapsed_seconds": elapsed, "http_status": response.status_code})
    try:
        body = response.json()
        raw_text = body["choices"][0]["message"]["content"]
        finish_reason = body["choices"][0].get("finish_reason")
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise ModelCallError("模型接口响应结构无效", details={"attempted": True, "elapsed_seconds": elapsed, "http_status": response.status_code, "response_body": response.text.replace(key, "[REDACTED]")}) from exc
    # 原始成功响应只含API返回正文；仍防御性移除意外回显的真实密钥。
    import json
    sanitized_body = json.loads(json.dumps(body, ensure_ascii=False).replace(key, "[REDACTED]"))
    return {"raw_text": sanitized_body["choices"][0]["message"]["content"], "model": sanitized_body.get("model", config.model), "usage": sanitized_body.get("usage", {}), "elapsed_seconds": elapsed, "finish_reason": finish_reason, "provider_response": sanitized_body, "attempted": True}
