"""S2 偏好业务层：有来源的偏好记录、确认/撤销，以及硬筛选与等权匹配排序。"""

from __future__ import annotations

import sqlite3
from typing import Any

from . import storage
from .storage import ConflictError, NotFoundError, StorageError, list_preferences

__all__ = [
    "ConflictError", "NotFoundError", "StorageError", "confirm", "hard_filter", "list_preferences",
    "match_and_rank", "record", "revoke",
]


def record(conn: sqlite3.Connection, subject: str, kind: str, original_text: str, explicit: bool, source: str) -> dict:
    """记录一条偏好：explicit=True 直接 confirmed，否则 pending 待顾问确认。"""
    return storage.add_preference(conn, subject=subject, kind=kind, original_text=original_text, explicit=explicit, source=source)


def confirm(conn: sqlite3.Connection, preference_id: int) -> dict:
    return storage.confirm_preference(conn, preference_id)


def revoke(conn: sqlite3.Connection, preference_id: int) -> dict:
    return storage.revoke_preference(conn, preference_id)


def _matchable_text(item: dict[str, Any]) -> str:
    return " ".join(str(item.get(key, "")) for key in ("name", "description", "sweetness"))


def hard_filter(products: list[dict], budget_cny: float | None = None, exclude_terms: list[str] | None = None) -> list[dict]:
    """价格上限与排除词硬过滤；budget 为 None 不过滤价格；设预算时价格未知的商品剔除（不暗中放宽预算）。"""
    selected = list(products)
    if budget_cny is not None:
        def within_budget(item: dict[str, Any]) -> bool:
            price = item.get("price_cny")
            if price is None:
                return False
            return float(price) <= float(budget_cny)
        selected = [item for item in selected if within_budget(item)]
    for term in [item for item in (exclude_terms or []) if item]:
        selected = [item for item in selected if term not in _matchable_text(item)]
    return selected


def match_and_rank(products: list[dict], likes: list[str], dislikes: list[str]) -> list[dict]:
    """等权匹配描述/名称/甜度：likes 命中加分、dislikes 命中减分；返回带 score 与 reasons，按分数降序（同分保持原顺序）。"""
    ranked = []
    for item in products:
        text = _matchable_text(item)
        score = 0
        reasons: list[str] = []
        for term in likes:
            if term and term in text:
                score += 1
                reasons.append(f"喜欢匹配：{term}")
        for term in dislikes:
            if term and term in text:
                score -= 1
                reasons.append(f"排除匹配：{term}")
        ranked.append({**item, "score": score, "reasons": reasons})
    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked
