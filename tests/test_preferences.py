"""S2 偏好业务层离线检查：记录/确认/撤销、硬筛选与等权排序；零真实模型调用。"""

import sqlite3
from pathlib import Path

import pytest

from qixu_advisor import preferences, storage
from qixu_advisor.data import PROJECT_ROOT, catalog_records, load_catalog
from qixu_advisor.storage import NotFoundError


@pytest.fixture
def conn(tmp_path: Path):
    connection = storage.connect_db(tmp_path / "test.sqlite3")
    storage.init_schema(connection)
    yield connection
    connection.close()


@pytest.fixture
def catalog_products() -> list[dict]:
    return catalog_records(load_catalog("products", root=PROJECT_ROOT))


def test_record_confirm_revoke_and_list(conn):
    created = preferences.record(conn, subject="C001", kind="like", original_text="我平时喜欢玫瑰", explicit=False, source="消息12")
    assert created["status"] == "pending"
    confirmed = preferences.confirm(conn, created["id"])
    assert confirmed["status"] == "confirmed"
    revoked = preferences.revoke(conn, created["id"])
    assert revoked["status"] == "revoked"
    with pytest.raises(NotFoundError):
        preferences.confirm(conn, 9999)
    explicit = preferences.record(conn, subject="C001", kind="budget", original_text="预算最多1400元", explicit=True, source="消息13")
    assert explicit["status"] == "confirmed"
    assert [item["kind"] for item in preferences.list_preferences(conn, subject="C001", status="confirmed")] == ["budget"]


def test_hard_filter_budget_cap_and_unknown_price(catalog_products):
    within = preferences.hard_filter(catalog_products, budget_cny=1000)
    assert {item["sku_id"] for item in within} == {"QINGLAN-50", "YANBO-30"}
    assert preferences.hard_filter(catalog_products, budget_cny=None) == catalog_products
    missing_price = [{"sku_id": "UNKNOWN-1", "name": "未知规格", "price_cny": None}]
    assert preferences.hard_filter(missing_price, budget_cny=1000) == []
    assert preferences.hard_filter(missing_price) == missing_price


def test_hard_filter_exclude_terms(catalog_products):
    filtered = preferences.hard_filter(catalog_products, exclude_terms=["玫瑰", "茶叶"])
    assert {item["name"] for item in filtered} == {"青岚", "砚泊"}
    assert preferences.hard_filter(catalog_products, exclude_terms=["不存在的词"]) == catalog_products


def test_match_and_rank_scores_and_reasons(catalog_products):
    ranked = preferences.match_and_rank(catalog_products, likes=["柑橘"], dislikes=["玫瑰"])
    scores = {item["sku_id"]: item["score"] for item in ranked}
    assert scores["QINGLAN-50"] == 1 and scores["MUGUANG-50"] == -1
    assert scores["YUBAI-50"] == 0
    order = [item["sku_id"] for item in ranked]
    assert order.index("QINGLAN-50") < order.index("YUBAI-50") < order.index("MUGUANG-50")
    qinglan = next(item for item in ranked if item["sku_id"] == "QINGLAN-50")
    assert "喜欢匹配：柑橘" in qinglan["reasons"]
    muguang = next(item for item in ranked if item["sku_id"] == "MUGUANG-50")
    assert "排除匹配：玫瑰" in muguang["reasons"]
    assert all("score" in item and "reasons" in item for item in ranked)


def test_match_and_rank_ties_keep_original_order():
    products = [
        {"sku_id": "A", "name": "香氛甲", "description": "清新", "sweetness": "低"},
        {"sku_id": "B", "name": "香氛乙", "description": "清新", "sweetness": "低"},
    ]
    ranked = preferences.match_and_rank(products, likes=["清新"], dislikes=[])
    assert [item["sku_id"] for item in ranked] == ["A", "B"]
    assert all(item["score"] == 1 for item in ranked)
