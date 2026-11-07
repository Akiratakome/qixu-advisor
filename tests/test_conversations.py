"""S2 会话业务层离线检查：快照往返与草稿动作；tmp_path SQLite，零真实模型调用。"""

import sqlite3
from pathlib import Path

import pytest

from qixu_advisor import conversations, storage
from qixu_advisor.models import GenerationRequest
from qixu_advisor.storage import ConflictError, NotFoundError


@pytest.fixture
def conn(tmp_path: Path):
    connection = storage.connect_db(tmp_path / "test.sqlite3")
    storage.init_schema(connection)
    yield connection
    connection.close()


def test_open_conversation_creates_and_reads_back(conn):
    created = conversations.open_conversation(conn, scenario="产品推荐", current_need="送朋友", budget_cny=1200)
    assert created["version"] == 1
    assert created["id"]
    reopened = conversations.open_conversation(conn, created["id"])
    assert reopened == created
    with pytest.raises(NotFoundError):
        conversations.open_conversation(conn, "CONV-404")


def test_append_message_and_snapshot_roundtrip(conn):
    storage.create_customer(conn, "C001", {"display_name": "林女士"})
    conversation = conversations.open_conversation(conn, customer_id="C001", scenario="产品推荐",
        settings={"recipient": {"relationship": "妹妹", "likes": ["柑橘"]}, "output_language": "en", "tone": "warm", "length": "short", "goal": "recommend"},
        current_need="为妹妹选香", budget_cny=1000, occasion=None, event_id=None, product_ids=["QINGLAN-50", "YUBAI-50"])
    first = conversations.append_message(conn, conversation["id"], "client", "妹妹喜欢柑橘，不喜欢甜香。", source="wechat", external_id="ext-1")
    assert first["new_version"] == 2
    second = conversations.append_message(conn, conversation["id"], "advisor", "我帮您对比两款柑橘调。", source="workbench")
    assert second["new_version"] == 3
    with pytest.raises(ConflictError):
        conversations.append_message(conn, conversation["id"], "client", "重放", source="wechat", external_id="ext-1")
    snapshot = conversations.snapshot_for_generation(conn, conversation["id"])
    assert snapshot["scenario"] == "产品推荐"
    assert snapshot["conversation_history"] == [
        {"role": "client", "content": "妹妹喜欢柑橘，不喜欢甜香。"},
        {"role": "advisor", "content": "我帮您对比两款柑橘调。"},
    ]
    assert snapshot["client_information"] == {
        "current_need": "为妹妹选香", "budget_cny": 1000,
        "recipient": {"relationship": "妹妹", "likes": ["柑橘"]},
    }
    assert snapshot["product_ids"] == ["QINGLAN-50", "YUBAI-50"]
    assert snapshot["client_id"] == "C001"
    assert snapshot["output_language"] == "en" and snapshot["tone"] == "warm"
    assert snapshot["length"] == "short" and snapshot["goal"] == "recommend"
    # 快照是 GenerationRequest 兼容的：补齐 scenario 后可直接校验。
    request = GenerationRequest.model_validate({**snapshot, "scenario": "产品推荐"})
    assert request.client_information["budget_cny"] == 1000
    assert len(request.conversation_history) == 2


def test_snapshot_settings_defaults_and_empty_fields(conn):
    conversation = conversations.open_conversation(conn)
    snapshot = conversations.snapshot_for_generation(conn, conversation["id"])
    assert snapshot["scenario"] is None
    assert snapshot["conversation_history"] == []
    assert snapshot["client_information"] == {}
    assert snapshot["product_ids"] == []
    assert snapshot["client_id"] is None
    assert snapshot["output_language"] == "zh-CN"
    assert snapshot["tone"] == "natural"
    assert snapshot["length"] == "standard"
    assert snapshot["goal"] is None


def test_record_draft_wrappers(conn):
    conversation = conversations.open_conversation(conn, scenario="产品推荐", current_need="送朋友")
    generation = storage.create_generation(conn, conversation["id"], "key-1", "{}", expected_version=1)
    revision = conversations.record_draft_revision(conn, generation["id"], "UI-001-C1", "机器原稿")
    assert revision["revision"] == 1
    action = conversations.record_draft_action(conn, revision["id"], "copied", copied_text="机器原稿", editor="顾问甲")
    assert action["action"] == "copied" and action["copied_text"] == "机器原稿"
    with pytest.raises(ValueError, match="草稿动作"):
        conversations.record_draft_action(conn, revision["id"], "sent")


def test_conversation_version_reads_after_messages(conn):
    conversation = conversations.open_conversation(conn)
    assert conversation["version"] == 1
    result = conversations.append_message(conn, conversation["id"], "client", "第一条")
    assert storage.get_conversation(conn, conversation["id"])["version"] == result["new_version"]
