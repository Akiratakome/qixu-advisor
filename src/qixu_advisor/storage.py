"""S2 会话存储：SQLite 短事务读写、版本乐观锁与幂等键；只返回普通业务数据。

QIXU_RUNTIME_DIR 环境变量指向运行目录（默认项目根 runtime/），数据库文件 qixu.sqlite3。
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .data import PROJECT_ROOT

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
DRAFT_ACTIONS = {"selected", "copied", "discarded"}


class StorageError(Exception):
    """存储层基础错误。"""


class NotFoundError(StorageError):
    """目标行不存在。"""


class ConflictError(StorageError):
    """版本冲突、重复外部键或幂等键内容不一致。"""


def _now() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="milliseconds")


RUNTIME_SETTING_KEYS = {"provider", "base_url", "model", "api_key", "temperature"}


def get_setting(conn: sqlite3.Connection, key: str) -> str | None:
    if key not in RUNTIME_SETTING_KEYS:
        raise ValueError(f"运行时设置键不在白名单：{key}（允许 {sorted(RUNTIME_SETTING_KEYS)}）")
    row = conn.execute("SELECT value FROM runtime_settings WHERE key = ?", (key,)).fetchone()
    return None if row is None else row["value"]


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    if key not in RUNTIME_SETTING_KEYS:
        raise ValueError(f"运行时设置键不在白名单：{key}（允许 {sorted(RUNTIME_SETTING_KEYS)}）")
    conn.execute("INSERT INTO runtime_settings (key, value, updated_at) VALUES (?, ?, ?) "
                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                 (key, value, _now()))
    conn.commit()


def runtime_dir() -> Path:
    return Path(os.environ.get("QIXU_RUNTIME_DIR") or PROJECT_ROOT / "runtime")


def default_db_path() -> Path:
    return runtime_dir() / "qixu.sqlite3"


def connect_db(path: str | Path | None = None) -> sqlite3.Connection:
    """创建 SQLite 连接（row_factory=Row、外键开启、timeout 5s）。

    check_same_thread=False：FastAPI 对同步 def 路由用线程池执行，依赖生成器的 __enter__ 与
    端点体/__exit__ 可能在不同线程访问同一连接。安全前提：每请求独占一条连接、同一连接
    不并发使用——SQLite 对象只允许跨线程顺序访问；并发写入仍由 busy timeout 处理，禁止共享并发连接。
    """
    conn = sqlite3.connect(str(path) if path is not None else str(default_db_path()), timeout=5.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """按文件名顺序执行 migrations/*.sql，并把最高迁移编号写入 meta.schema_version。"""
    scripts = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not scripts:
        raise StorageError(f"未找到数据库迁移脚本：{MIGRATIONS_DIR}")
    version = 0
    for script in scripts:
        try:
            version = int(script.name.split("_", 1)[0])
        except ValueError:
            continue
        conn.executescript(script.read_text(encoding="utf-8"))
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)", (str(version),))
    conn.commit()


def _row(row: sqlite3.Row | None) -> dict:
    return {key: row[key] for key in row.keys()}


def _decode_customer(row: sqlite3.Row) -> dict:
    result = _row(row)
    result["profile"] = json.loads(result.pop("profile_json"))
    return result


def _decode_conversation(row: sqlite3.Row) -> dict:
    result = _row(row)
    result["settings"] = json.loads(result.pop("settings_json"))
    result["product_ids"] = json.loads(result.pop("product_ids_json"))
    return result


def _decode_generation(row: sqlite3.Row) -> dict:
    result = _row(row)
    result["running"] = result["status"] == "running"
    return result


def _decode_preference(row: sqlite3.Row) -> dict:
    result = _row(row)
    result["explicit"] = bool(result["explicit"])
    return result


# ---------- 客户 ----------

def create_customer(conn: sqlite3.Connection, customer_id: str, profile: dict[str, Any], *, version: int = 1) -> dict:
    now = _now()
    conn.execute("INSERT INTO customers (id, version, profile_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                 (customer_id, version, json.dumps(profile, ensure_ascii=False), now, now))
    conn.commit()
    return get_customer(conn, customer_id)


def get_customer(conn: sqlite3.Connection, customer_id: str) -> dict:
    row = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"客户不存在：{customer_id}")
    return _decode_customer(row)


def list_customers(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM customers ORDER BY id").fetchall()
    return [_decode_customer(row) for row in rows]


def update_customer(conn: sqlite3.Connection, customer_id: str, profile: dict[str, Any], expected_version: int) -> dict:
    row = conn.execute("SELECT version FROM customers WHERE id = ?", (customer_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"客户不存在：{customer_id}")
    if row["version"] != expected_version:
        raise ConflictError(f"客户版本冲突：当前 {row['version']}，期望 {expected_version}")
    conn.execute("UPDATE customers SET version = ?, profile_json = ?, updated_at = ? WHERE id = ?",
                 (expected_version + 1, json.dumps(profile, ensure_ascii=False), _now(), customer_id))
    conn.commit()
    return get_customer(conn, customer_id)


# ---------- 会话 ----------

def create_conversation(conn: sqlite3.Connection, conversation_id: str, *, customer_id: str | None = None, scenario: str | None = None,
                        settings: dict[str, Any] | None = None, current_need: str | None = None, budget_cny: float | None = None,
                        occasion: str | None = None, event_id: str | None = None, product_ids: list[str] | None = None,
                        status: str = "active", version: int = 1) -> dict:
    now = _now()
    conn.execute(
        "INSERT INTO conversations (id, customer_id, scenario, settings_json, current_need, budget_cny, occasion, event_id, product_ids_json, status, version, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (conversation_id, customer_id, scenario, json.dumps(settings or {}, ensure_ascii=False), current_need, budget_cny, occasion, event_id,
         json.dumps(product_ids or [], ensure_ascii=False), status, version, now, now))
    conn.commit()
    return get_conversation(conn, conversation_id)


def get_conversation(conn: sqlite3.Connection, conversation_id: str) -> dict:
    row = conn.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"会话不存在：{conversation_id}")
    return _decode_conversation(row)


def list_conversations(conn: sqlite3.Connection, customer_id: str | None = None) -> list[dict]:
    if customer_id is None:
        rows = conn.execute("SELECT * FROM conversations ORDER BY id").fetchall()
    else:
        rows = conn.execute("SELECT * FROM conversations WHERE customer_id = ? ORDER BY id", (customer_id,)).fetchall()
    return [_decode_conversation(row) for row in rows]


def update_conversation(conn: sqlite3.Connection, conversation_id: str, expected_version: int, **fields: Any) -> dict:
    row = conn.execute("SELECT version FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"会话不存在：{conversation_id}")
    if row["version"] != expected_version:
        raise ConflictError(f"会话版本冲突：当前 {row['version']}，期望 {expected_version}")
    if not fields:
        raise ValueError("至少提供一个会话字段")
    allowed = {"scenario", "current_need", "budget_cny", "occasion", "event_id", "status", "customer_id", "settings_json", "product_ids_json"}
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"未知会话字段：{sorted(unknown)}")
    assignments = []
    values: list[Any] = []
    for key, value in fields.items():
        if key in {"settings_json", "product_ids_json"}:
            if value is None:
                continue
            if not isinstance(value, str):
                value = json.dumps(value, ensure_ascii=False)
        assignments.append(f"{key} = ?")
        values.append(value)
    if not assignments:
        raise ValueError("至少提供一个会话字段")
    values.extend([expected_version + 1, _now(), conversation_id])
    conn.execute(f"UPDATE conversations SET {', '.join(assignments)}, version = ?, updated_at = ? WHERE id = ?", values)
    conn.commit()
    return get_conversation(conn, conversation_id)


def add_message(conn: sqlite3.Connection, conversation_id: str, role: str, content: str, *, source: str = "manual", external_id: str | None = None, expected_version: int) -> dict:
    row = conn.execute("SELECT version FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"会话不存在：{conversation_id}")
    if row["version"] != expected_version:
        raise ConflictError(f"会话版本冲突：当前 {row['version']}，期望 {expected_version}")
    now = _now()
    new_version = expected_version + 1
    try:
        cursor = conn.execute("INSERT INTO messages (conversation_id, role, content, source, external_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                              (conversation_id, role, content, source, external_id, now))
        conn.execute("UPDATE conversations SET version = ?, updated_at = ? WHERE id = ?", (new_version, now, conversation_id))
        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise ConflictError(f"消息外部键重复：conversation={conversation_id} source={source} external_id={external_id}") from exc
    message = _row(conn.execute("SELECT * FROM messages WHERE id = ?", (cursor.lastrowid,)).fetchone())
    return {"message": message, "new_version": new_version}


def list_messages(conn: sqlite3.Connection, conversation_id: str) -> list[dict]:
    row = conn.execute("SELECT id FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"会话不存在：{conversation_id}")
    rows = conn.execute("SELECT * FROM messages WHERE conversation_id = ? ORDER BY id", (conversation_id,)).fetchall()
    return [_row(item) for item in rows]


# ---------- 生成与草稿 ----------

def create_generation(conn: sqlite3.Connection, conversation_id: str, request_key: str, payload_json: str, expected_version: int) -> dict:
    existing = conn.execute("SELECT * FROM generations WHERE conversation_id = ? AND request_key = ?", (conversation_id, request_key)).fetchone()
    if existing is not None:
        if existing["payload_json"] != payload_json:
            raise ConflictError(f"幂等键内容不一致：{conversation_id}/{request_key}")
        return _decode_generation(existing)
    row = conn.execute("SELECT version FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"会话不存在：{conversation_id}")
    if row["version"] != expected_version:
        raise ConflictError(f"会话版本冲突：当前 {row['version']}，期望 {expected_version}")
    generation_id = uuid.uuid4().hex
    conn.execute("INSERT INTO generations (id, conversation_id, request_key, payload_json, status, run_id, case_id, expected_version, created_at) "
                 "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (generation_id, conversation_id, request_key, payload_json, "running", None, None, expected_version, _now()))
    conn.commit()
    return get_generation(conn, generation_id)


def get_generation(conn: sqlite3.Connection, generation_id: str) -> dict:
    row = conn.execute("SELECT * FROM generations WHERE id = ?", (generation_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"生成任务不存在：{generation_id}")
    return _decode_generation(row)


def complete_generation(conn: sqlite3.Connection, generation_id: str, status: str, run_id: str | None, case_id: str | None) -> None:
    row = conn.execute("SELECT id FROM generations WHERE id = ?", (generation_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"生成任务不存在：{generation_id}")
    conn.execute("UPDATE generations SET status = ?, run_id = ?, case_id = ? WHERE id = ?", (status, run_id, case_id, generation_id))
    conn.commit()


def add_draft_revision(conn: sqlite3.Connection, generation_id: str, candidate_id: str, text: str) -> dict:
    row = conn.execute("SELECT id FROM generations WHERE id = ?", (generation_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"生成任务不存在：{generation_id}")
    current = conn.execute("SELECT COALESCE(MAX(revision), 0) AS value FROM draft_revisions WHERE generation_id = ? AND candidate_id = ?",
                           (generation_id, candidate_id)).fetchone()
    revision = int(current["value"]) + 1
    now = _now()
    cursor = conn.execute("INSERT INTO draft_revisions (generation_id, candidate_id, revision, text, created_at) VALUES (?, ?, ?, ?, ?)",
                          (generation_id, candidate_id, revision, text, now))
    conn.commit()
    return {"id": cursor.lastrowid, "generation_id": generation_id, "candidate_id": candidate_id, "revision": revision, "text": text, "created_at": now}


def add_draft_action(conn: sqlite3.Connection, draft_revision_id: int, action: str, copied_text: str = "", editor: str | None = None) -> dict:
    if action not in DRAFT_ACTIONS:
        raise ValueError(f"草稿动作须为 {sorted(DRAFT_ACTIONS)} 之一")
    row = conn.execute("SELECT id FROM draft_revisions WHERE id = ?", (draft_revision_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"草稿修订不存在：{draft_revision_id}")
    now = _now()
    cursor = conn.execute("INSERT INTO draft_actions (draft_revision_id, action, copied_text, editor, created_at) VALUES (?, ?, ?, ?, ?)",
                          (draft_revision_id, action, copied_text, editor, now))
    conn.commit()
    return {"id": cursor.lastrowid, "draft_revision_id": draft_revision_id, "action": action, "copied_text": copied_text, "editor": editor, "created_at": now}


# ---------- 偏好 ----------

def add_preference(conn: sqlite3.Connection, subject: str, kind: str, original_text: str, explicit: bool, source: str) -> dict:
    status = "confirmed" if explicit else "pending"
    now = _now()
    cursor = conn.execute("INSERT INTO preferences (subject, kind, original_text, source, explicit, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                          (subject, kind, original_text, source, int(bool(explicit)), status, now, now))
    conn.commit()
    return get_preference(conn, int(cursor.lastrowid))


def get_preference(conn: sqlite3.Connection, preference_id: int) -> dict:
    row = conn.execute("SELECT * FROM preferences WHERE id = ?", (preference_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"偏好记录不存在：{preference_id}")
    return _decode_preference(row)


def _set_preference_status(conn: sqlite3.Connection, preference_id: int, status: str) -> dict:
    row = conn.execute("SELECT id FROM preferences WHERE id = ?", (preference_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"偏好记录不存在：{preference_id}")
    conn.execute("UPDATE preferences SET status = ?, updated_at = ? WHERE id = ?", (status, _now(), preference_id))
    conn.commit()
    return get_preference(conn, preference_id)


def confirm_preference(conn: sqlite3.Connection, preference_id: int) -> dict:
    return _set_preference_status(conn, preference_id, "confirmed")


def revoke_preference(conn: sqlite3.Connection, preference_id: int) -> dict:
    return _set_preference_status(conn, preference_id, "revoked")


def list_preferences(conn: sqlite3.Connection, subject: str | None = None, status: str | None = None) -> list[dict]:
    clauses = []
    values: list[Any] = []
    if subject is not None:
        clauses.append("subject = ?")
        values.append(subject)
    if status is not None:
        clauses.append("status = ?")
        values.append(status)
    query = "SELECT * FROM preferences"
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY id"
    rows = conn.execute(query, values).fetchall()
    return [_decode_preference(item) for item in rows]
