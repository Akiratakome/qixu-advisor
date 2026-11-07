"""只表达业务数据；此模块不读磁盘、不调用模型。"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCENARIOS = ("生日与节庆", "产品推荐", "购后关怀", "沉睡唤醒", "活动邀请", "价格异议")
Scenario = Literal["生日与节庆", "产品推荐", "购后关怀", "沉睡唤醒", "活动邀请", "价格异议"]
Status = Literal["success", "needs_input", "contact_blocked", "technical_failure"]


def valid_id(value: str) -> str:
    """业务 ID 同时用于本地目录，拒绝路径片段。"""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", value):
        raise ValueError("ID 只能含英文字母、数字、下划线和短横线，长度 1–96")
    return value


class GenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario: Scenario
    client_information: dict[str, Any] = Field(default_factory=dict)
    conversation_history: list[dict[str, Any]] = Field(default_factory=list)
    product_ids: list[str] = Field(default_factory=list)
    event_id: str | None = None
    occasion: str | None = None
    client_id: str | None = None
    # 写作设置；旧 jsonl 无这些字段时默认值生效。goal=None 表示按场景默认，生成时解析。
    output_language: Literal["zh-CN", "en"] = "zh-CN"
    tone: Literal["natural", "warm", "direct"] = "natural"
    length: Literal["short", "standard"] = "standard"
    goal: Literal["answer", "recommend", "next_step"] | None = None

    @field_validator("conversation_history")
    @classmethod
    def check_history(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for turn in value:
            if turn.get("role") not in {"user", "assistant", "client", "customer", "advisor"}:
                raise ValueError("聊天角色须为 user/client/customer 或 assistant/advisor")
            if not isinstance(turn.get("content"), str) or not turn["content"].strip():
                raise ValueError("聊天消息必须有非空 content")
        return value


class CaseSpec(BaseModel):
    # source、family 与诊断标记属于实验元数据，永远不自动传入模型。
    model_config = ConfigDict(extra="allow")

    case_id: str
    family_id: str
    split: Literal["dev", "holdout", "boundary"]
    request: GenerationRequest
    source: dict[str, Any] = Field(default_factory=dict)

    _case_id = field_validator("case_id")(valid_id)
    _family_id = field_validator("family_id")(valid_id)


class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    text: str = Field(min_length=1, max_length=3000)

    @field_validator("text")
    @classmethod
    def non_empty_text(cls, text: str) -> str:
        # 语言校验移到生成层按 output_language 进行；这里只保留非空与长度上限。
        text = text.strip()
        if not text:
            raise ValueError("候选文本不能为空")
        return text


class GenerationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    case_id: str
    status: Status
    candidates: list[Candidate] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    error: str | None = None
    fact_references: list[dict[str, Any]] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_candidates(self) -> "GenerationResult":
        if self.status == "success":
            if len(self.candidates) != 3:
                raise ValueError("成功结果必须恰好三条候选")
            if len({item.candidate_id for item in self.candidates}) != 3:
                raise ValueError("候选 ID 必须唯一")
            if len({item.text for item in self.candidates}) != 3:
                raise ValueError("三条候选不可完全重复")
        elif self.candidates:
            raise ValueError("非成功结果不得包含候选")
        return self
