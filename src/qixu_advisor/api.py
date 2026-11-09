"""S2 FastAPI 接口层：HTTP 路由与传输。不读取提示、不直接调用模型供应商、不持有连接。

对 storage/conversations/preferences 的适配说明（与 core 落地实现的差异，集成时由 lead 对齐）：

1. generations.status 单列同时承担任务/业务状态：占位为 "running"，完成后写入业务终态
   （success/needs_input/contact_blocked/technical_failure），异常时写 "interrupted"。
   因此 GET 恢复查询没有 missing_fields/warnings/error 明细列，POST 同步返回全部明细。
2. storage.add_message 对外部键重复抛 ConflictError：本层先按 (会话, source, external_id)
   查询，已存在直接 200 返回原消息；插入仍冲突时回查去重，只有版本冲突才上抛 409。
3. storage.add_draft_revision 自动递增修订号、无 expected_revision 乐观锁：本层先读该候选
   当前最大修订号比较，不一致 409，一致才追加（409 防覆盖另一修订）。
4. preferences 表没有 customer_id 列，subject 列存客户 ID；/customers/{id}/preferences
   用 subject=customer_id 读写。
5. customers.profile_json 是整份档案 dict：PATCH 读-改-写整份 profile，未给字段保持不变。
6. conversations 没有 client_information 列：临时资料经 settings.recipient、current_need、
   budget_cny、occasion 表达（见 conversations.snapshot_for_generation）。
7. 草稿的对外 id 为该候选初始修订行 id（稳定锚点），PATCH/actions 按
   (generation_id, candidate_id) 定位修订链。
8. 生成任务的 run_id/case_id 由本层生成（web- 前缀十六进制），artifacts/runs 留档继续可用。
9. storage.update_conversation 按字段 key 直接拼列名：settings/product_ids 会生成不存在的列
   （no such column: settings）。API 层 PATCH 会话时把这两个字段映射为 storage 列名
   （settings_json/product_ids_json）并统一 json.dumps 后单条 UPDATE（版本乐观锁语义一致），
   无 JSON 字段时仍走 storage 更新。
10. 运行时模型配置：storage.get_setting/set_setting 读写 runtime_settings 表，本层组装
    ModelConfig——运行时 api_key 非空则 runtime 优先（缺失字段回退 .env），否则整体回退
    .env；records.create_run(config=...) 把本次实际配置写入 manifest（凭据经 public_config
    排除），generate/analyze_conversation 以 config= 接收，begin_case 的模型参数快照守卫一致放行。
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import starlette.exceptions as _starlette_exceptions
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import SecretStr, ValidationError

from . import conversations, generation as generation_module, preferences, records, storage
from .api_models import (
    AnalyzeIn,
    AnalyzeOut,
    CatalogItemOut,
    ConversationDetailOut,
    ConversationIn,
    ConversationOut,
    ConversationPatch,
    CustomerIn,
    CustomerOut,
    CustomerPatch,
    DraftActionIn,
    DraftActionOut,
    DraftOut,
    DraftPatch,
    GenerationIn,
    GenerationOut,
    MessageIn,
    MessageOut,
    ModelSettingsOut,
    ModelSettingsUpdate,
    PreferenceIn,
    PreferenceOut,
    PreferencePatch,
    SeedCustomersOut,
)
from .data import PROJECT_ROOT, catalog_records, load_catalog
from .generation import generate
from .model import ModelConfig, get_config as env_get_config
from .models import GenerationRequest
from .storage import ConflictError, NotFoundError, StorageError


# ---------- 映射助手 ----------


def _customer_out(row: dict[str, Any]) -> CustomerOut:
    return CustomerOut(
        customer_id=row["id"],
        version=row["version"],
        profile=row.get("profile") or {},
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _conversation_out(row: dict[str, Any]) -> ConversationOut:
    return ConversationOut(
        conversation_id=row["id"],
        customer_id=row.get("customer_id"),
        scenario=row.get("scenario"),
        settings=row.get("settings") or {},
        current_need=row.get("current_need"),
        budget_cny=row.get("budget_cny"),
        occasion=row.get("occasion"),
        event_id=row.get("event_id"),
        product_ids=row.get("product_ids") or [],
        status=row["status"],
        version=row["version"],
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _message_out(row: dict[str, Any], *, conversation_version: int | None = None) -> MessageOut:
    return MessageOut(
        message_id=row["id"],
        conversation_id=row["conversation_id"],
        role=row["role"],
        content=row["content"],
        source=row["source"],
        external_id=row.get("external_id"),
        created_at=row.get("created_at"),
        conversation_version=conversation_version,
    )


def _preference_out(row: dict[str, Any]) -> PreferenceOut:
    return PreferenceOut(
        preference_id=row["id"],
        subject=row["subject"],
        kind=row["kind"],
        original_text=row["original_text"],
        source=row["source"],
        explicit=bool(row["explicit"]),
        status=row["status"],
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _now_iso() -> str:
    """与 storage._now 相同的东八区毫秒时间戳，供本层直接写库的路径使用。"""
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="milliseconds")


def _runtime_settings(conn: sqlite3.Connection) -> dict[str, str]:
    """runtime_settings 表内容（按 storage 白名单逐键读取）；存储接口不可用时视为未配置。"""
    keys = getattr(storage, "RUNTIME_SETTING_KEYS", {"provider", "base_url", "model", "api_key", "temperature"})
    settings: dict[str, str] = {}
    try:
        for key in keys:
            value = storage.get_setting(conn, key)
            if value is not None:
                settings[key] = value
    except (AttributeError, sqlite3.Error):
        return {}
    return settings


def _effective_model_config(conn: sqlite3.Connection, root: Path) -> tuple[ModelConfig, str]:
    """请求时的有效模型配置：runtime_settings 含非空 api_key 则采用运行时配置
    （缺失字段逐个回退 .env），否则整体回退 .env 配置。返回 (config, source)。"""
    runtime = _runtime_settings(conn)
    try:
        base = env_get_config(root)
    except (ValueError, TypeError):
        base = ModelConfig()
    api_key = (runtime.get("api_key") or "").strip()
    if not api_key:
        return base, "env"
    temperature = base.temperature
    if "temperature" in runtime:
        try:
            candidate = float(runtime["temperature"])
        except (TypeError, ValueError):
            candidate = None
        if candidate is not None and 0 <= candidate <= 2:
            temperature = candidate
    effective = ModelConfig(
        provider=(runtime.get("provider") or "").strip() or base.provider,
        base_url=(runtime.get("base_url") or "").strip().rstrip("/") or base.base_url,
        model=(runtime.get("model") or "").strip() or base.model,
        api_key=SecretStr(api_key),
        temperature=temperature,
    )
    return effective, "runtime"


def _apply_cold_start_defaults(snapshot: dict[str, Any]) -> dict[str, Any]:
    """会话无消息时的冷启动默认输入：只补缺失字段，是显式输入而非放宽引擎校验。
    返回实际应用的变更（非空表示已应用）。"""
    scenario = snapshot.get("scenario")
    client_information = snapshot.setdefault("client_information", {})
    changes: dict[str, Any] = {}
    if scenario == "生日与节庆" and not client_information.get("occasion"):
        client_information["occasion"] = "客户生日（默认缘由，可改）"
        changes["occasion"] = client_information["occasion"]
    if scenario == "购后关怀" and not client_information.get("current_need"):
        client_information["current_need"] = "客户刚完成购买，做一次跟进问候"
        changes["current_need"] = client_information["current_need"]
    if scenario == "沉睡唤醒" and not snapshot.get("client_id") and not any(client_information.values()):
        client_information["relationship"] = "老客户，长时间未联系（默认）"
        changes["relationship"] = client_information["relationship"]
    return changes


def _check_cold_start_required(snapshot: dict[str, Any]) -> None:
    """会话无消息时的必填校验：活动邀请必须已选活动，产品推荐/价格异议必须有一句需求。
    不满足时 422 并带 fields（无默认值）。"""
    scenario = snapshot.get("scenario")
    client_information = snapshot.get("client_information") or {}
    fields: dict[str, str] = {}
    if scenario == "活动邀请" and not snapshot.get("event_id"):
        fields["event_id"] = "活动邀请需要先选择具体活动（无默认值）"
    if scenario in {"产品推荐", "价格异议"} and not client_information.get("current_need"):
        fields["current_need"] = "该场景需要一句客户需求或原话（无默认值）"
    if fields:
        raise RequestValidationError(
            errors=[{"type": "value_error", "loc": ("body", key), "msg": message, "input": None} for key, message in fields.items()]
        )


def _model_status(conn: sqlite3.Connection, root: Path) -> ModelSettingsOut:
    """模型配置状态：只返回状态与公开参数，绝不返回密钥本身。"""
    config, source = _effective_model_config(conn, root)
    api_key_set = bool(config.api_key.get_secret_value().strip())
    if api_key_set:
        missing: list[str] = []
    else:
        try:
            env_get_config(root)
        except (ValueError, TypeError):
            missing = ["模型参数格式无效，请检查 .env"]
        else:
            missing = ["DEEPSEEK_API_KEY"]
    return ModelSettingsOut(
        configured=api_key_set,
        provider=config.provider,
        model=config.model,
        base_url=config.base_url,
        missing=missing,
        api_key_set=api_key_set,
        source=source,
    )


def _find_message(conn: sqlite3.Connection, conversation_id: str, source: str, external_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM messages WHERE conversation_id = ? AND source = ? AND external_id = ?",
        (conversation_id, source, external_id),
    ).fetchone()
    return dict(row) if row is not None else None


def _find_generation(conn: sqlite3.Connection, conversation_id: str, request_key: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM generations WHERE conversation_id = ? AND request_key = ?", (conversation_id, request_key)
    ).fetchone()
    return dict(row) if row is not None else None


def _running_generation_count(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS count FROM generations WHERE status = 'running'").fetchone()
    return int(row["count"])


def _draft_rows(conn: sqlite3.Connection, generation_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM draft_revisions WHERE generation_id = ? ORDER BY candidate_id, revision", (generation_id,)
    ).fetchall()
    return [dict(row) for row in rows]


def _drafts_out(conn: sqlite3.Connection, generation_id: str) -> list[DraftOut]:
    chains: dict[str, list[dict[str, Any]]] = {}
    for row in _draft_rows(conn, generation_id):
        chains.setdefault(row["candidate_id"], []).append(row)
    drafts: list[DraftOut] = []
    for candidate_id, chain in chains.items():
        chain.sort(key=lambda item: item["revision"])
        anchor = chain[0]
        latest = chain[-1]
        drafts.append(
            DraftOut(
                draft_id=anchor["id"],
                generation_id=generation_id,
                candidate_id=candidate_id,
                revision=latest["revision"],
                text=latest["text"],
                source="machine" if latest["revision"] == 1 else "edited",
                created_at=latest["created_at"],
            )
        )
    drafts.sort(key=lambda item: item.candidate_id)
    return drafts


def _draft_anchor(conn: sqlite3.Connection, draft_id: int) -> dict[str, Any]:
    """按初始修订行 id 定位候选草稿，并读出该候选当前最大修订号。"""
    row = conn.execute("SELECT * FROM draft_revisions WHERE id = ?", (draft_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"草稿不存在：{draft_id}")
    anchor = dict(row)
    current = conn.execute(
        "SELECT COALESCE(MAX(revision), 0) AS value FROM draft_revisions WHERE generation_id = ? AND candidate_id = ?",
        (anchor["generation_id"], anchor["candidate_id"]),
    ).fetchone()
    anchor["current_revision"] = int(current["value"])
    return anchor


def _generation_out(
    conn: sqlite3.Connection, row: dict[str, Any], *, business_fields: dict[str, Any] | None = None
) -> GenerationOut:
    """generations.status 单列：running/interrupted 为任务态，其余值为业务终态。"""
    status = row["status"]
    if status == "running":
        task_status, business_status = "running", None
    elif status == "interrupted":
        task_status, business_status = "interrupted", None
    else:
        task_status, business_status = "completed", status
    fields = business_fields or {}
    running = bool(row["running"]) if "running" in row else row["status"] == "running"
    return GenerationOut(
        generation_id=row["id"],
        conversation_id=row["conversation_id"],
        task_status=task_status,
        business_status=business_status,
        snapshot_version=row["expected_version"],
        run_id=row.get("run_id"),
        case_id=row.get("case_id"),
        drafts=_drafts_out(conn, row["id"]),
        missing_fields=fields.get("missing_fields") or [],
        warnings=fields.get("warnings") or [],
        error=fields.get("error"),
        created_at=row.get("created_at"),
        running=running,
    )


# ---------- 应用装配 ----------


def create_app(db_path: str | Path, *, root: Path = PROJECT_ROOT, static_dir: Path | None = None) -> FastAPI:
    """按 db_path 创建 FastAPI 应用；每请求短连接（yield 注入、显式关闭）。

    仅支持文件路径 SQLite（`:memory:` 会因每请求独立连接而丢库）。启动时执行迁移并把
    遗留 running 任务标为 interrupted；重启不自动重调模型。

    static_dir 指向 S3 React 构建产物目录（web/dist）：目录含 index.html 时挂载静态文件，
    并把非 /api 前缀的未匹配 GET 回退到 index.html（SPA）；未知 /api/* 仍是 JSON 404。
    目录缺失或没有 index.html 时不挂载，行为与之前完全一致。
    """
    db_path = str(db_path)
    if db_path != ":memory:":
        Path(db_path).resolve().parent.mkdir(parents=True, exist_ok=True)
    app = FastAPI(title="栖序 QIXU 顾问工作台 API", version="0.1.0")
    app.state.db_path = db_path
    app.state.root = Path(root)
    static_index: Path | None = None
    if static_dir is not None:
        static_dir = Path(static_dir)
        candidate_index = static_dir / "index.html"
        if candidate_index.is_file():
            static_index = candidate_index
    app.state.static_index = static_index

    with storage.connect_db(db_path) as conn:
        storage.init_schema(conn)
        conn.execute("UPDATE generations SET status = 'interrupted' WHERE status = 'running'")
        conn.commit()

    def get_conn():
        conn = storage.connect_db(db_path)
        try:
            yield conn
        finally:
            conn.close()

    def error_response(request: Request, status_code: int, code: str, message: str, fields: dict[str, Any] | None = None) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None) or uuid.uuid4().hex[:16]
        body: dict[str, Any] = {"error": {"code": code, "message": message}, "request_id": request_id}
        if fields:
            body["error"]["fields"] = fields
        return JSONResponse(status_code=status_code, content=body, headers={"X-Request-Id": request_id})

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = uuid.uuid4().hex[:16]
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        return response

    # 注意注册顺序：Starlette 按注册顺序做 isinstance 匹配，子类必须在前。
    @app.exception_handler(NotFoundError)
    async def not_found_handler(request: Request, exc: NotFoundError):
        return error_response(request, 404, "not_found", str(exc))

    @app.exception_handler(ConflictError)
    async def conflict_handler(request: Request, exc: ConflictError):
        return error_response(request, 409, "conflict", str(exc))

    @app.exception_handler(StorageError)
    async def storage_error_handler(request: Request, exc: StorageError):
        return error_response(request, 500, "storage_error", "存储操作失败，请稍后重试")

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        fields: dict[str, Any] = {}
        for error in exc.errors():
            location = ".".join(str(part) for part in error.get("loc", ()) if part != "body") or "body"
            fields[location] = error.get("msg", "参数不合法")
        return error_response(request, 422, "validation_error", "请求参数不合法", fields=fields)

    # 路由未匹配等场景抛出 starlette.exceptions.HTTPException；fastapi.exceptions.HTTPException
    # 是其子类（部分版本为独立子类），因此同时注册两个键，保证两种 404/405/429/422/502 都走统一错误体。
    @app.exception_handler(_starlette_exceptions.HTTPException)
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        # SPA 回退：静态目录激活时，非 /api 前缀的未匹配 GET 一律返回 index.html；
        # /api 前缀的 404 保持 JSON 错误体（前端路由深链刷新可恢复，接口错误可解析）。
        if exc.status_code == 404 and app.state.static_index is not None:
            if request.method == "GET" and not request.url.path.startswith("/api"):
                return FileResponse(app.state.static_index)
        code = {404: "not_found", 405: "method_not_allowed", 409: "conflict", 422: "validation_error", 429: "busy",
                500: "internal", 502: "upstream_error"}.get(exc.status_code, "error")
        return error_response(request, exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        # 不返回栈、凭据或供应商原文。
        return error_response(request, 500, "internal", "服务器内部错误，请稍后重试")

    # ---------- 客户 ----------

    @app.get("/api/v1/customers", response_model=list[CustomerOut])
    def list_customers(conn: sqlite3.Connection = Depends(get_conn)):
        return [_customer_out(row) for row in storage.list_customers(conn)]

    @app.post("/api/v1/customers", status_code=201, response_model=CustomerOut)
    def create_customer(body: CustomerIn, conn: sqlite3.Connection = Depends(get_conn)):
        customer_id = body.client_id or f"web-{uuid.uuid4().hex[:12]}"
        if body.client_id:
            existing = conn.execute("SELECT 1 FROM customers WHERE id = ?", (customer_id,)).fetchone()
            if existing is not None:
                raise ConflictError(f"客户已存在：{customer_id}")
        return _customer_out(storage.create_customer(conn, customer_id, body.profile_fields()))

    @app.post("/api/v1/customers/seed", response_model=SeedCustomersOut)
    def seed_customers(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
        """把 data/fictional/customers.json 的示例客户写入 customers 表：幂等，
        已存在 client_id 跳过；profile_json 为整份档案，client_id 为表主键 id。"""
        records_list = catalog_records(load_catalog("customers", root=request.app.state.root))
        created: list[str] = []
        skipped: list[str] = []
        for record in records_list:
            client_id = record.get("client_id") or record.get("customer_id") or record.get("id")
            if not client_id:
                continue
            existing = conn.execute("SELECT 1 FROM customers WHERE id = ?", (client_id,)).fetchone()
            if existing is not None:
                skipped.append(client_id)
                continue
            storage.create_customer(conn, client_id, dict(record))
            created.append(client_id)
        return SeedCustomersOut(created=created, skipped=skipped, total=len(created) + len(skipped))

    @app.get("/api/v1/customers/{customer_id}", response_model=CustomerOut)
    def get_customer(customer_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        return _customer_out(storage.get_customer(conn, customer_id))

    @app.patch("/api/v1/customers/{customer_id}", response_model=CustomerOut)
    def patch_customer(customer_id: str, body: CustomerPatch, conn: sqlite3.Connection = Depends(get_conn)):
        current = storage.get_customer(conn, customer_id)
        profile = dict(current.get("profile") or {})
        for key, value in body.model_dump(exclude={"expected_version"}).items():
            if value is not None:
                profile[key] = value
        return _customer_out(storage.update_customer(conn, customer_id, profile, body.expected_version))

    # ---------- 会话与消息 ----------

    @app.get("/api/v1/conversations", response_model=list[ConversationOut])
    def list_conversations(customer_id: str | None = Query(default=None), conn: sqlite3.Connection = Depends(get_conn)):
        return [_conversation_out(row) for row in storage.list_conversations(conn, customer_id=customer_id)]

    @app.post("/api/v1/conversations", status_code=201, response_model=ConversationOut)
    def create_conversation(body: ConversationIn, conn: sqlite3.Connection = Depends(get_conn)):
        if body.customer_id:
            storage.get_customer(conn, body.customer_id)
        fields = body.model_dump(exclude={"settings"})
        fields["settings"] = body.settings.model_dump(exclude_none=True) if body.settings else None
        return _conversation_out(conversations.open_conversation(conn, None, **fields))

    @app.get("/api/v1/conversations/{conversation_id}", response_model=ConversationDetailOut)
    def get_conversation(conversation_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        row = storage.get_conversation(conn, conversation_id)
        messages = [_message_out(item) for item in storage.list_messages(conn, conversation_id)]
        return ConversationDetailOut(**_conversation_out(row).model_dump(), messages=messages)

    @app.patch("/api/v1/conversations/{conversation_id}", response_model=ConversationOut)
    def patch_conversation(conversation_id: str, body: ConversationPatch, conn: sqlite3.Connection = Depends(get_conn)):
        fields = {
            key: value
            for key, value in body.model_dump(exclude={"expected_version", "settings"}).items()
            if value is not None
        }
        if body.settings is not None:
            # 与 create_conversation 一致：排除 None（goal 未显式设置时不写 null），
            # 其余非 None 项（含 length/tone 等默认值）随整份字典落盘。
            fields["settings"] = body.settings.model_dump(exclude_none=True)
        if fields.get("customer_id"):
            storage.get_customer(conn, fields["customer_id"])
        has_json_fields = "settings" in fields or "product_ids" in fields
        if fields and not has_json_fields:
            # 无 JSON 字段：字段名与列名一致，直接走 storage 更新。
            return _conversation_out(storage.update_conversation(conn, conversation_id, body.expected_version, **fields))
        # storage.update_conversation 按字段 key 直接拼列名，settings/product_ids 会生成不存在的列
        # （no such column: settings）。本层把 body 字段映射为 storage 列名（settings_json/
        # product_ids_json），统一 json.dumps 序列化后单条 UPDATE；其余字段按列名直传，
        # 版本乐观锁与 storage 语义一致（不匹配 409、不存在 404）。
        current = storage.get_conversation(conn, conversation_id)
        if current["version"] != body.expected_version:
            raise ConflictError(f"会话版本冲突：当前 {current['version']}，期望 {body.expected_version}")
        assignments: list[str] = []
        values: list[Any] = []
        for key, value in fields.items():
            if key == "settings":
                assignments.append("settings_json = ?")
                values.append(json.dumps(value, ensure_ascii=False))
            elif key == "product_ids":
                assignments.append("product_ids_json = ?")
                values.append(json.dumps(value, ensure_ascii=False))
            else:
                assignments.append(f"{key} = ?")
                values.append(value)
        assignments.append("version = ?")
        assignments.append("updated_at = ?")
        values.extend([body.expected_version + 1, _now_iso(), conversation_id])
        conn.execute(f"UPDATE conversations SET {', '.join(assignments)} WHERE id = ?", values)
        conn.commit()
        return _conversation_out(storage.get_conversation(conn, conversation_id))

    @app.post("/api/v1/conversations/{conversation_id}/messages", status_code=201, response_model=MessageOut)
    def post_message(conversation_id: str, body: MessageIn, conn: sqlite3.Connection = Depends(get_conn)):
        storage.get_conversation(conn, conversation_id)
        external_id = (body.external_id or "").strip() or None
        if external_id:
            existing = _find_message(conn, conversation_id, body.source, external_id)
            if existing is not None:
                version = storage.get_conversation(conn, conversation_id)["version"]
                return JSONResponse(status_code=200, content=_message_out(existing, conversation_version=version).model_dump(mode="json"))
        try:
            result = conversations.append_message(conn, conversation_id, body.role, body.content, source=body.source, external_id=external_id)
        except ConflictError:
            if external_id:
                existing = _find_message(conn, conversation_id, body.source, external_id)
                if existing is not None:
                    version = storage.get_conversation(conn, conversation_id)["version"]
                    return JSONResponse(status_code=200, content=_message_out(existing, conversation_version=version).model_dump(mode="json"))
            raise
        return _message_out(result["message"], conversation_version=result["new_version"])

    # ---------- 目录与模型状态 ----------

    @app.get("/api/v1/catalog", response_model=list[CatalogItemOut])
    def get_catalog(
        request: Request, product_id: str | None = Query(default=None), sku_id: str | None = Query(default=None)
    ):
        items = catalog_records(load_catalog("products", root=request.app.state.root))
        if product_id:
            items = [item for item in items if item.get("product_id") == product_id]
        if sku_id:
            items = [item for item in items if item.get("sku_id") == sku_id]
        keys = ("sku_id", "product_id", "name", "volume_ml", "price_cny", "currency", "description", "source")
        return [CatalogItemOut(**{key: item.get(key) for key in keys}) for item in items]

    @app.get("/api/v1/settings/model", response_model=ModelSettingsOut)
    def get_model_settings(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
        # 运行时配置状态（runtime_settings 优先、.env 回退）；绝不返回密钥。
        return _model_status(conn, request.app.state.root)

    @app.put("/api/v1/settings/model", response_model=ModelSettingsOut)
    def put_model_settings(body: ModelSettingsUpdate, request: Request, conn: sqlite3.Connection = Depends(get_conn)):
        # 字段白名单由 extra=forbid 保证；URL/温度等校验由模型完成（422 带 fields）。
        # api_key 允许空串以清除；统一以字符串落库，密钥不进入任何响应。
        for key, value in body.model_dump(exclude_none=True).items():
            storage.set_setting(conn, key, "" if value is None else str(value))
        return _model_status(conn, request.app.state.root)

    # ---------- 对话分析 ----------

    @app.post("/api/v1/analyze", response_model=AnalyzeOut)
    def analyze_conversation_endpoint(body: AnalyzeIn, request: Request, conn: sqlite3.Connection = Depends(get_conn)):
        # 同步一次调用；analyze_conversation 内部失败不重试。结构非法/模型失败 → 502，
        # 本端配置问题（缺少提示文件/未配置密钥）→ 500；不回显栈与凭据。
        try:
            config, _source = _effective_model_config(conn, request.app.state.root)
            result = generation_module.analyze_conversation(
                [turn.model_dump() for turn in body.conversation_history],
                body.client_information,
                root=request.app.state.root,
                config=config,
            )
        except ValueError as exc:
            message = str(exc)
            if "结构不合格" in message or "对话分析" in message:
                raise HTTPException(status_code=502, detail=message) from exc
            raise HTTPException(status_code=500, detail=message) from exc
        request_id = getattr(request.state, "request_id", None) or uuid.uuid4().hex[:16]
        return AnalyzeOut(
            scenario=result.scenario,
            current_need=result.current_need,
            missing_questions=result.missing_questions,
            request_id=request_id,
        )

    # ---------- 生成与草稿 ----------

    @app.post("/api/v1/conversations/{conversation_id}/generations", response_model=GenerationOut)
    def create_generation(
        conversation_id: str,
        body: GenerationIn,
        request: Request,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        key = (idempotency_key or body.idempotency_key or "").strip()
        if not key:
            raise HTTPException(status_code=422, detail="缺少幂等键：请提供 Idempotency-Key 头或请求体 idempotency_key")
        conversation = storage.get_conversation(conn, conversation_id)
        snapshot = conversations.snapshot_for_generation(conn, conversation_id)
        if body.settings is not None:
            for field in ("output_language", "tone", "length", "goal"):
                snapshot[field] = getattr(body.settings, field)
        # 冷启动默认输入：仅会话无消息且相应字段缺失时应用（显式默认值，不放宽引擎校验）；
        # 应用时在幂等 payload 中记录 cold_start_defaults_applied（响应体不暴露该标记）。
        messages_count = len(snapshot.get("conversation_history") or [])
        cold_start_changes: dict[str, Any] = {}
        if messages_count == 0:
            cold_start_changes = _apply_cold_start_defaults(snapshot)
        payload_object: dict[str, Any] = {
            "expected_version": body.expected_version,
            "settings": body.settings.model_dump() if body.settings else None,
        }
        if cold_start_changes:
            payload_object["cold_start_defaults_applied"] = True
        payload = json.dumps(payload_object, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        # 幂等键优先：同键同内容返回首次任务；同键不同内容 409。之后再校验版本与繁忙状态。
        existing = _find_generation(conn, conversation_id, key)
        if existing is not None:
            if existing["payload_json"] != payload:
                raise ConflictError(f"幂等键内容不一致：{conversation_id}/{key}")
            return _generation_out(conn, existing)
        if conversation["version"] != body.expected_version:
            raise ConflictError(f"会话版本冲突：当前 {conversation['version']}，期望 {body.expected_version}")
        if not snapshot.get("scenario"):
            raise HTTPException(status_code=422, detail="会话未设置场景，无法生成；请先 PATCH 会话补充场景")
        if messages_count == 0:
            _check_cold_start_required(snapshot)
        try:
            generation_request = GenerationRequest.model_validate(snapshot)
        except ValidationError as exc:
            first = exc.errors()[0] if exc.errors() else {"msg": "快照结构非法"}
            raise HTTPException(status_code=422, detail=f"会话快照不满足生成要求：{first.get('msg', '结构非法')}") from exc
        if _running_generation_count(conn) > 0:
            raise HTTPException(status_code=429, detail="已有进行中的生成任务，请稍后再试")
        try:
            generation = storage.create_generation(conn, conversation_id, key, payload, body.expected_version)
        except sqlite3.IntegrityError:
            raced = _find_generation(conn, conversation_id, key)
            if raced is not None:
                if raced["payload_json"] != payload:
                    raise ConflictError(f"幂等键内容不一致：{conversation_id}/{key}")
                return _generation_out(conn, raced)
            raise
        run_id = f"web-{generation['id'][:12]}"
        case_id = f"web-{generation['id'][:24]}"
        # 有效模型配置：运行时设置优先（api_key 非空），否则回退 .env。
        config, _source = _effective_model_config(conn, request.app.state.root)
        try:
            # 先创建固定运行清单（artifacts/runs/<run_id>/manifest.json）；config= 传入本次实际
            # 有效配置（凭据经 public_config 排除），generate 内部 begin_case 依赖该清单并做
            # 版本/参数快照校验。创建失败时不留 running 占位：标 interrupted 后上抛，由统一错误处理转 500。
            records.create_run([case_id], run_id=run_id, execution_mode="real", root=request.app.state.root, config=config)
        except Exception:
            storage.complete_generation(conn, generation["id"], "interrupted", run_id, case_id)
            raise
        try:
            # 阻塞调用：同步执行生成；缺项/拒联系/未配置密钥由 generation.generate 内部短路，不调用模型。
            result = generate(generation_request, run_id, case_id, root=request.app.state.root, config=config)
        except Exception:
            storage.complete_generation(conn, generation["id"], "interrupted", run_id, case_id)
            raise
        try:
            drafts: list[DraftOut] = []
            if result.status == "success":
                for candidate in result.candidates:
                    row = conversations.record_draft_revision(conn, generation["id"], candidate.candidate_id, candidate.text)
                    drafts.append(
                        DraftOut(
                            draft_id=row["id"],
                            generation_id=generation["id"],
                            candidate_id=candidate.candidate_id,
                            revision=row["revision"],
                            text=row["text"],
                            source="machine",
                            created_at=row["created_at"],
                        )
                    )
            storage.complete_generation(conn, generation["id"], result.status, run_id, case_id)
        except Exception:
            storage.complete_generation(conn, generation["id"], "interrupted", run_id, case_id)
            raise
        completed = storage.get_generation(conn, generation["id"])
        return _generation_out(
            conn,
            completed,
            business_fields={"missing_fields": result.missing_fields, "warnings": result.warnings, "error": result.error},
        )

    @app.get("/api/v1/generations/{generation_id}", response_model=GenerationOut)
    def get_generation(generation_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        return _generation_out(conn, storage.get_generation(conn, generation_id))

    @app.patch("/api/v1/drafts/{draft_id}", response_model=DraftOut)
    def patch_draft(draft_id: int, body: DraftPatch, conn: sqlite3.Connection = Depends(get_conn)):
        anchor = _draft_anchor(conn, draft_id)
        if anchor["current_revision"] != body.expected_revision:
            raise ConflictError(f"草稿修订冲突：当前 {anchor['current_revision']}，期望 {body.expected_revision}")
        row = conversations.record_draft_revision(conn, anchor["generation_id"], anchor["candidate_id"], body.text)
        return DraftOut(
            draft_id=anchor["id"],
            generation_id=anchor["generation_id"],
            candidate_id=anchor["candidate_id"],
            revision=row["revision"],
            text=row["text"],
            source="edited",
            created_at=row["created_at"],
        )

    @app.post("/api/v1/drafts/{draft_id}/actions", status_code=201, response_model=DraftActionOut)
    def post_draft_action(draft_id: int, body: DraftActionIn, conn: sqlite3.Connection = Depends(get_conn)):
        anchor = _draft_anchor(conn, draft_id)
        base_revision = body.base_revision if body.base_revision is not None else anchor["current_revision"]
        revision_row = conn.execute(
            "SELECT * FROM draft_revisions WHERE generation_id = ? AND candidate_id = ? AND revision = ?",
            (anchor["generation_id"], anchor["candidate_id"], base_revision),
        ).fetchone()
        if revision_row is None:
            raise NotFoundError(f"草稿修订不存在：候选 {anchor['candidate_id']} 修订 {base_revision}")
        action = conversations.record_draft_action(conn, int(revision_row["id"]), body.action, copied_text=body.copied_text or "")
        return DraftActionOut(
            action_id=action["id"],
            draft_revision_id=action["draft_revision_id"],
            action=action["action"],
            copied_text=action["copied_text"],
            editor=action.get("editor"),
            created_at=action["created_at"],
        )

    # ---------- 偏好 ----------

    @app.get("/api/v1/customers/{customer_id}/preferences", response_model=list[PreferenceOut])
    def list_preferences(customer_id: str, conn: sqlite3.Connection = Depends(get_conn)):
        storage.get_customer(conn, customer_id)
        return [_preference_out(row) for row in preferences.list_preferences(conn, subject=customer_id)]

    @app.post("/api/v1/customers/{customer_id}/preferences", status_code=201, response_model=PreferenceOut)
    def record_preference(customer_id: str, body: PreferenceIn, conn: sqlite3.Connection = Depends(get_conn)):
        storage.get_customer(conn, customer_id)
        row = preferences.record(
            conn, subject=customer_id, kind=body.kind, original_text=body.original_text, explicit=body.explicit, source=body.source
        )
        return _preference_out(row)

    @app.patch("/api/v1/preferences/{preference_id}", response_model=PreferenceOut)
    def patch_preference(preference_id: int, body: PreferencePatch, conn: sqlite3.Connection = Depends(get_conn)):
        if body.action == "confirm":
            return _preference_out(preferences.confirm(conn, preference_id))
        return _preference_out(preferences.revoke(conn, preference_id))

    # 静态托管必须在所有 API 路由之后注册：/api 路由先匹配，未知 /api/* 由 404 处理器返回 JSON 错误体。
    if static_index is not None:
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="web-dist")

    return app
