"""S2 会话业务层：把保存的会话转成生成快照；网络调用不持有事务。"""

from __future__ import annotations

import sqlite3
import uuid
from typing import Any

from . import storage
from .storage import ConflictError, NotFoundError, StorageError, create_conversation, get_conversation, list_conversations, list_messages

__all__ = [
    "ConflictError", "NotFoundError", "StorageError", "append_message", "create_conversation", "get_conversation",
    "list_conversations", "list_messages", "open_conversation", "record_draft_action", "record_draft_revision",
    "snapshot_for_generation",
]


def open_conversation(conn: sqlite3.Connection, conversation_id: str | None = None, **fields: Any) -> dict:
    """新建（version=1，ID 自动生成）或按 id 读回会话。"""
    if conversation_id is None:
        conversation_id = uuid.uuid4().hex
        return create_conversation(conn, conversation_id, **fields)
    return get_conversation(conn, conversation_id)


def append_message(conn: sqlite3.Connection, conversation_id: str, role: str, content: str, source: str = "manual", external_id: str | None = None) -> dict:
    """追加消息：用会话当前版本做乐观锁；返回 {message, new_version}。"""
    conversation = get_conversation(conn, conversation_id)
    return storage.add_message(conn, conversation_id, role, content, source=source, external_id=external_id, expected_version=conversation["version"])


def snapshot_for_generation(conn: sqlite3.Connection, conversation_id: str) -> dict:
    """输出 GenerationRequest 兼容 dict；scenario 可能为空，由调用方补充。"""
    conversation = get_conversation(conn, conversation_id)
    messages = list_messages(conn, conversation_id)
    settings = conversation.get("settings") or {}
    client_information: dict[str, Any] = {}
    if conversation.get("current_need"):
        client_information["current_need"] = conversation["current_need"]
    if conversation.get("budget_cny") is not None:
        client_information["budget_cny"] = conversation["budget_cny"]
    if conversation.get("occasion"):
        client_information["occasion"] = conversation["occasion"]
    if settings.get("recipient"):
        client_information["recipient"] = settings["recipient"]
    return {
        "scenario": conversation.get("scenario"),
        "conversation_history": [{"role": item["role"], "content": item["content"]} for item in messages],
        "client_information": client_information,
        "product_ids": conversation.get("product_ids") or [],
        "event_id": conversation.get("event_id"),
        "client_id": conversation.get("customer_id"),
        "output_language": settings.get("output_language", "zh-CN"),
        "tone": settings.get("tone", "natural"),
        "length": settings.get("length", "standard"),
        "goal": settings.get("goal"),
    }


def record_draft_revision(conn: sqlite3.Connection, generation_id: str, candidate_id: str, text: str) -> dict:
    return storage.add_draft_revision(conn, generation_id, candidate_id, text)


def record_draft_action(conn: sqlite3.Connection, draft_revision_id: int, action: str, copied_text: str = "", editor: str | None = None) -> dict:
    """草稿动作薄封装；action ∈ {selected, copied, discarded}，copied 必须携带实际 copied_text。"""
    return storage.add_draft_action(conn, draft_revision_id, action, copied_text=copied_text, editor=editor)
