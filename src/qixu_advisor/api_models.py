"""FastAPI 传输模型：请求/响应结构。此模块不读磁盘、不读数据库、不调用模型。

命名与 storage/conversations/preferences 的落库字段对齐（见各模型注释）；HTTP 层再映射为
对外字段名（如 storage 的 customers.id 对外为 customer_id）。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import Scenario

OutputLanguage = Literal["zh-CN", "en"]
Tone = Literal["natural", "warm", "direct"]
Length = Literal["short", "standard"]
Goal = Literal["answer", "recommend", "next_step"]
MessageRole = Literal["user", "client", "customer", "assistant", "advisor"]
DraftActionKind = Literal["selected", "copied", "discarded"]


class WritingSettings(BaseModel):
    """写作设置：默认值与 models.GenerationRequest 一致；None 表示沿用会话/场景默认。"""

    model_config = ConfigDict(extra="forbid")

    output_language: OutputLanguage = "zh-CN"
    tone: Tone = "natural"
    length: Length = "standard"
    goal: Goal | None = None


# ---------- 客户 ----------


class CustomerIn(BaseModel):
    """新建客户档案；client_id 缺省时服务端自动生成。profile 字段合并为整份档案 dict 落库。"""

    model_config = ConfigDict(extra="forbid")

    client_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$")
    display_name: str | None = None
    contact_permission: Literal["allowed", "denied"] | None = None
    relationship: str | None = None
    buyer: dict[str, Any] | None = None
    long_term_preferences: dict[str, Any] | None = None

    def profile_fields(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in self.model_dump(exclude={"client_id"}).items()
            if value is not None
        }


class CustomerPatch(BaseModel):
    """明确修改客户档案：expected_version 乐观锁；只合并给出的字段到现有 profile。"""

    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    display_name: str | None = None
    contact_permission: Literal["allowed", "denied"] | None = None
    relationship: str | None = None
    buyer: dict[str, Any] | None = None
    long_term_preferences: dict[str, Any] | None = None


class CustomerOut(BaseModel):
    """storage.customers 行对外形状；profile 为整份档案 dict。"""

    model_config = ConfigDict(extra="ignore")

    customer_id: str
    version: int
    profile: dict[str, Any]
    created_at: str | None = None
    updated_at: str | None = None


# ---------- 会话与消息 ----------


class ConversationIn(BaseModel):
    """新建会话：客户、场景、需求、设置、预算、活动与商品范围。

    临时客户资料按 storage 合同表达：recipient 写入 settings，其余写入 current_need/budget_cny/occasion。
    """

    model_config = ConfigDict(extra="forbid")

    customer_id: str | None = None
    scenario: Scenario | None = None
    settings: WritingSettings | None = None
    current_need: str | None = None
    budget_cny: float | None = Field(default=None, ge=0)
    occasion: str | None = None
    event_id: str | None = None
    product_ids: list[str] = Field(default_factory=list)


class ConversationPatch(BaseModel):
    """修改会话：expected_version 乐观锁；None 字段不修改。"""

    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    customer_id: str | None = None
    scenario: Scenario | None = None
    settings: WritingSettings | None = None
    current_need: str | None = None
    budget_cny: float | None = Field(default=None, ge=0)
    occasion: str | None = None
    event_id: str | None = None
    product_ids: list[str] | None = None
    status: Literal["active", "closed"] | None = None


class ConversationOut(BaseModel):
    """storage.conversations 行对外形状。"""

    model_config = ConfigDict(extra="ignore")

    conversation_id: str
    customer_id: str | None = None
    scenario: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)
    current_need: str | None = None
    budget_cny: float | None = None
    occasion: str | None = None
    event_id: str | None = None
    product_ids: list[str] = Field(default_factory=list)
    status: str
    version: int
    created_at: str | None = None
    updated_at: str | None = None


class MessageIn(BaseModel):
    """追加消息；external_id 在（会话, source）范围内去重。role 只允许生成核心认可的角色。"""

    model_config = ConfigDict(extra="forbid")

    role: MessageRole
    content: str = Field(min_length=1)
    source: str = Field(default="manual", min_length=1)
    external_id: str | None = None


class MessageOut(BaseModel):
    """storage.messages 行对外形状；conversation_version 为写入后的会话新版本（去重返回当前版本）。"""

    model_config = ConfigDict(extra="ignore")

    message_id: int
    conversation_id: str
    role: str
    content: str
    source: str
    external_id: str | None = None
    created_at: str | None = None
    conversation_version: int | None = None


class ConversationDetailOut(ConversationOut):
    messages: list[MessageOut] = Field(default_factory=list)


# ---------- 生成与草稿 ----------


class GenerationIn(BaseModel):
    """创建生成任务：expected_version 锁定会话快照；幂等键优先取 Idempotency-Key 头，其次取本字段。"""

    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    idempotency_key: str | None = Field(default=None, min_length=1)
    settings: WritingSettings | None = None


class DraftOut(BaseModel):
    """一个候选草稿：draft_id 为该候选初始修订行 id（稳定锚点），revision/text 为最新修订。"""

    model_config = ConfigDict(extra="ignore")

    draft_id: int
    generation_id: str
    candidate_id: str
    revision: int
    text: str
    source: str = "machine"  # machine=机器原稿，edited=顾问编辑稿
    created_at: str | None = None


class GenerationOut(BaseModel):
    """生成任务：task_status ∈ running/completed/interrupted；business_status ∈
    success/needs_input/contact_blocked/technical_failure（GET 恢复时缺失明细字段为空）。

    snapshot_version 即创建任务时锁定的会话版本（storage.generations.expected_version）。
    """

    model_config = ConfigDict(extra="ignore")

    generation_id: str
    conversation_id: str
    task_status: str
    business_status: str | None = None
    snapshot_version: int
    run_id: str | None = None
    case_id: str | None = None
    drafts: list[DraftOut] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    created_at: str | None = None
    running: bool = False


class DraftPatch(BaseModel):
    """编辑草稿：在 expected_revision 之后追加一条新修订；与当前最新修订不一致时 409。"""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=3000)
    expected_revision: int = Field(ge=1)


class DraftActionIn(BaseModel):
    """草稿动作留证；copied 必须携带实际 copied_text 与基准 revision（不等于 saved/sent）。"""

    model_config = ConfigDict(extra="forbid")

    action: DraftActionKind
    copied_text: str | None = None
    base_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def check_copied_evidence(self) -> "DraftActionIn":
        if self.action == "copied":
            if not self.copied_text or not self.copied_text.strip():
                raise ValueError("copied 动作必须携带实际 copied_text")
            if self.base_revision is None:
                raise ValueError("copied 动作必须携带基准 revision")
        return self


class DraftActionOut(BaseModel):
    """storage.draft_actions 行对外形状。"""

    model_config = ConfigDict(extra="ignore")

    action_id: int
    draft_revision_id: int
    action: str
    copied_text: str = ""
    editor: str | None = None
    created_at: str | None = None


# ---------- 偏好 ----------


class PreferenceIn(BaseModel):
    """记录一条有来源的偏好；explicit=True 直接 confirmed，否则 pending 待顾问确认。"""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(min_length=1)
    original_text: str = Field(min_length=1)
    source: str = Field(min_length=1)
    explicit: bool = True


class PreferencePatch(BaseModel):
    """确认或撤销一条偏好。"""

    model_config = ConfigDict(extra="forbid")

    action: Literal["confirm", "revoke"]


class PreferenceOut(BaseModel):
    """storage.preferences 行对外形状（subject 列存客户 ID）。"""

    model_config = ConfigDict(extra="ignore")

    preference_id: int
    subject: str
    kind: str
    original_text: str
    source: str
    explicit: bool
    status: str
    created_at: str | None = None
    updated_at: str | None = None


# ---------- 目录与设置 ----------


class CatalogItemOut(BaseModel):
    """商品目录项：名称、规格、价格、描述、来源。"""

    model_config = ConfigDict(extra="ignore")

    sku_id: str
    product_id: str
    name: str
    volume_ml: int | float | None = None
    price_cny: int | float
    currency: str = "CNY"
    description: str | None = None
    source: str | None = None


class ModelSettingsOut(BaseModel):
    """模型与资料状态（model.config_status）：绝不包含密钥。"""

    model_config = ConfigDict(extra="ignore")

    configured: bool
    provider: str
    model: str | None = None
    base_url: str | None = None
    missing: list[str] = Field(default_factory=list)


# ---------- 错误 ----------


class ErrorDetail(BaseModel):
    code: str
    message: str
    fields: dict[str, Any] | None = None


class ErrorBody(BaseModel):
    error: ErrorDetail
    request_id: str
