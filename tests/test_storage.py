"""S2 存储层离线检查：tmp_path SQLite、短事务与约束；零真实模型调用。"""

import sqlite3
import threading
from pathlib import Path

import pytest

from qixu_advisor import storage
from qixu_advisor.storage import ConflictError, NotFoundError, StorageError


@pytest.fixture
def conn(tmp_path: Path):
    connection = storage.connect_db(tmp_path / "test.sqlite3")
    storage.init_schema(connection)
    yield connection
    connection.close()


def test_connect_db_configuration(tmp_path: Path):
    connection = storage.connect_db(tmp_path / "config.sqlite3")
    assert connection.row_factory is sqlite3.Row
    assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    connection.close()


def test_connect_db_allows_sequential_cross_thread_access(tmp_path: Path):
    """uvicorn 线程池场景：连接在主线程创建，另一线程顺序执行 SELECT，再回到主线程继续使用。"""
    connection = storage.connect_db(tmp_path / "cross-thread.sqlite3")
    storage.init_schema(connection)
    storage.create_customer(connection, "C001", {"display_name": "林女士"})
    result: dict = {}
    errors: list = []

    def select_in_other_thread():
        try:
            row = connection.execute("SELECT COUNT(*) AS total FROM customers").fetchone()
            result["total"] = row["total"]
        except Exception as exc:  # 测试需要捕获跨线程异常并回传主线程断言
            errors.append(exc)

    thread = threading.Thread(target=select_in_other_thread)
    thread.start()
    thread.join()
    assert errors == []
    assert result["total"] == 1
    # 回到主线程仍可顺序使用同一连接。
    assert storage.get_customer(connection, "C001")["id"] == "C001"
    connection.close()


def test_init_schema_creates_tables_and_meta(conn):
    names = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"customers", "conversations", "messages", "preferences", "generations", "draft_revisions", "draft_actions", "meta", "runtime_settings"} <= names
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    assert row is not None and row["value"] == "2"


def test_runtime_settings_get_set_and_whitelist(conn):
    assert storage.get_setting(conn, "model") is None
    storage.set_setting(conn, "model", "deepseek-flash")
    assert storage.get_setting(conn, "model") == "deepseek-flash"
    storage.set_setting(conn, "model", "custom-model")
    assert storage.get_setting(conn, "model") == "custom-model"
    storage.set_setting(conn, "api_key", "runtime-secret")
    assert storage.get_setting(conn, "api_key") == "runtime-secret"
    storage.set_setting(conn, "temperature", "0.3")
    assert storage.get_setting(conn, "temperature") == "0.3"
    with pytest.raises(ValueError, match="白名单"):
        storage.set_setting(conn, "not_a_key", "x")
    with pytest.raises(ValueError, match="白名单"):
        storage.get_setting(conn, "not_a_key")


def test_customer_crud_version_conflict_and_missing(conn):
    created = storage.create_customer(conn, "C001", {"display_name": "林女士", "likes": ["柑橘"]})
    assert created["id"] == "C001" and created["version"] == 1
    assert created["profile"] == {"display_name": "林女士", "likes": ["柑橘"]}
    assert {"id", "version", "profile", "created_at", "updated_at"} <= set(created)
    updated = storage.update_customer(conn, "C001", {"display_name": "林女士", "likes": ["柑橘", "清爽木质"]}, expected_version=1)
    assert updated["version"] == 2 and "清爽木质" in updated["profile"]["likes"]
    with pytest.raises(ConflictError):
        storage.update_customer(conn, "C001", {"display_name": "旧版本写入"}, expected_version=1)
    with pytest.raises(NotFoundError):
        storage.get_customer(conn, "C404")
    with pytest.raises(NotFoundError):
        storage.update_customer(conn, "C404", {}, expected_version=1)
    storage.create_customer(conn, "A002", {"display_name": "乙客户"})
    assert [item["id"] for item in storage.list_customers(conn)] == ["A002", "C001"]


def test_conversation_crud_version_and_field_validation(conn):
    storage.create_customer(conn, "C001", {"display_name": "林女士"})
    conversation = storage.create_conversation(conn, "CONV-1", customer_id="C001", scenario="产品推荐",
        settings={"output_language": "en", "recipient": {"relationship": "妹妹"}}, current_need="为妹妹选香",
        budget_cny=1000, occasion="生日", event_id="EVT-CITRUS", product_ids=["QINGLAN-50", "YUBAI-50"])
    assert conversation["version"] == 1 and conversation["status"] == "active"
    assert conversation["settings"] == {"output_language": "en", "recipient": {"relationship": "妹妹"}}
    assert conversation["product_ids"] == ["QINGLAN-50", "YUBAI-50"]
    assert conversation["budget_cny"] == 1000 and conversation["customer_id"] == "C001"
    updated = storage.update_conversation(conn, "CONV-1", expected_version=1, current_need="为妹妹选柑橘香", budget_cny=1100)
    assert updated["version"] == 2 and updated["current_need"] == "为妹妹选柑橘香" and updated["budget_cny"] == 1100
    with pytest.raises(ConflictError):
        storage.update_conversation(conn, "CONV-1", expected_version=1, current_need="冲突写入")
    with pytest.raises(ValueError, match="未知会话字段"):
        storage.update_conversation(conn, "CONV-1", expected_version=2, not_a_field="x")
    with pytest.raises(NotFoundError):
        storage.get_conversation(conn, "CONV-404")
    assert [item["id"] for item in storage.list_conversations(conn)] == ["CONV-1"]
    assert [item["id"] for item in storage.list_conversations(conn, customer_id="C001")] == ["CONV-1"]
    assert storage.list_conversations(conn, customer_id="C404") == []


def test_update_conversation_raw_json_columns_and_empty_fields(conn):
    storage.create_conversation(conn, "CONV-1", scenario="产品推荐", current_need="旧需求")
    # settings_json 传 dict 落库后可读回 dict；product_ids_json 列表往返。
    updated = storage.update_conversation(conn, "CONV-1", expected_version=1,
        settings_json={"output_language": "en", "recipient": {"relationship": "妹妹"}},
        product_ids_json=["QINGLAN-50", "YUBAI-50"])
    assert updated["version"] == 2
    assert updated["settings"] == {"output_language": "en", "recipient": {"relationship": "妹妹"}}
    assert updated["product_ids"] == ["QINGLAN-50", "YUBAI-50"]
    # settings_json 传字符串原样落库。
    updated2 = storage.update_conversation(conn, "CONV-1", expected_version=2, settings_json='{"output_language": "zh-CN"}')
    assert updated2["settings"] == {"output_language": "zh-CN"}
    # 传 None 跳过：字段保持原值，其余字段正常更新。
    updated3 = storage.update_conversation(conn, "CONV-1", expected_version=3, settings_json=None, product_ids_json=None, status="paused")
    assert updated3["settings"] == {"output_language": "zh-CN"}
    assert updated3["product_ids"] == ["QINGLAN-50", "YUBAI-50"]
    assert updated3["status"] == "paused"
    # 空字段集合与全 None 跳过均报 ValueError。
    with pytest.raises(ValueError, match="至少提供"):
        storage.update_conversation(conn, "CONV-1", expected_version=4)
    with pytest.raises(ValueError, match="至少提供"):
        storage.update_conversation(conn, "CONV-1", expected_version=4, settings_json=None)
    # 未知字段与版本冲突语义保持。
    with pytest.raises(ValueError, match="未知会话字段"):
        storage.update_conversation(conn, "CONV-1", expected_version=4, not_a_field="x")
    with pytest.raises(ConflictError):
        storage.update_conversation(conn, "CONV-1", expected_version=3, current_need="旧版本写入")


def test_add_message_bumps_version_dedupes_external_and_lists(conn):
    storage.create_conversation(conn, "CONV-1", scenario="价格异议", current_need="觉得贵")
    with pytest.raises(ConflictError):
        storage.add_message(conn, "CONV-1", "client", "版本不对", expected_version=2)
    with pytest.raises(NotFoundError):
        storage.add_message(conn, "CONV-404", "client", "会话不存在", expected_version=1)
    first = storage.add_message(conn, "CONV-1", "client", "1180元有点贵。", source="wechat", external_id="ext-1", expected_version=1)
    assert first["new_version"] == 2
    message = first["message"]
    assert {"id", "conversation_id", "role", "content", "source", "external_id", "created_at"} <= set(message)
    assert message["role"] == "client" and message["source"] == "wechat" and message["external_id"] == "ext-1"
    with pytest.raises(ConflictError, match="重复"):
        storage.add_message(conn, "CONV-1", "client", "重放同一条", source="wechat", external_id="ext-1", expected_version=2)
    second = storage.add_message(conn, "CONV-1", "advisor", "我帮您核对一下。", source="workbench", expected_version=2)
    assert second["new_version"] == 3
    messages = storage.list_messages(conn, "CONV-1")
    assert [item["id"] for item in messages] == [message["id"], second["message"]["id"]]
    assert [item["content"] for item in messages] == ["1180元有点贵。", "我帮您核对一下。"]
    assert storage.get_conversation(conn, "CONV-1")["version"] == 3
    with pytest.raises(NotFoundError):
        storage.list_messages(conn, "CONV-404")


def test_generation_idempotency_and_completion(conn):
    storage.create_conversation(conn, "CONV-1", scenario="产品推荐", current_need="送朋友")
    payload = '{"scenario": "产品推荐", "client_information": {}}'
    generation = storage.create_generation(conn, "CONV-1", "key-1", payload, expected_version=1)
    assert generation["status"] == "running" and generation["running"] is True
    assert {"id", "conversation_id", "request_key", "payload_json", "status", "run_id", "case_id", "expected_version", "created_at", "running"} <= set(generation)
    replay = storage.create_generation(conn, "CONV-1", "key-1", payload, expected_version=1)
    assert replay["id"] == generation["id"]
    with pytest.raises(ConflictError, match="幂等"):
        storage.create_generation(conn, "CONV-1", "key-1", '{"changed": true}', expected_version=1)
    with pytest.raises(ConflictError):
        storage.create_generation(conn, "CONV-1", "key-2", payload, expected_version=99)
    with pytest.raises(NotFoundError):
        storage.create_generation(conn, "CONV-404", "key-3", payload, expected_version=1)
    with pytest.raises(NotFoundError):
        storage.get_generation(conn, "GEN-404")
    storage.complete_generation(conn, generation["id"], "success", "run-1", "CASE-1")
    completed = storage.get_generation(conn, generation["id"])
    assert completed["status"] == "success" and completed["run_id"] == "run-1" and completed["case_id"] == "CASE-1"
    assert completed["running"] is False


def test_draft_revisions_per_candidate_and_actions(conn):
    storage.create_conversation(conn, "CONV-1", scenario="产品推荐", current_need="送朋友")
    generation = storage.create_generation(conn, "CONV-1", "key-1", "{}", expected_version=1)
    with pytest.raises(NotFoundError):
        storage.add_draft_revision(conn, "GEN-404", "C1", "文本")
    first = storage.add_draft_revision(conn, generation["id"], "CONV-C1", "机器原稿一")
    second = storage.add_draft_revision(conn, generation["id"], "CONV-C2", "机器原稿二")
    third = storage.add_draft_revision(conn, generation["id"], "CONV-C1", "编辑稿一")
    assert (first["revision"], second["revision"], third["revision"]) == (1, 1, 2)
    assert {"id", "generation_id", "candidate_id", "revision", "text", "created_at"} <= set(first)
    with pytest.raises(ValueError, match="草稿动作"):
        storage.add_draft_action(conn, first["id"], "sent")
    with pytest.raises(NotFoundError):
        storage.add_draft_action(conn, 9999, "selected")
    selected = storage.add_draft_action(conn, third["id"], "selected", editor="顾问甲")
    assert selected["action"] == "selected" and selected["editor"] == "顾问甲"
    copied = storage.add_draft_action(conn, third["id"], "copied", copied_text="编辑稿一（复制时的实际文本）", editor="顾问甲")
    assert copied["action"] == "copied" and copied["copied_text"] == "编辑稿一（复制时的实际文本）"
    discarded = storage.add_draft_action(conn, second["id"], "discarded")
    assert discarded["action"] == "discarded"


def test_preferences_flow_and_filters(conn):
    explicit = storage.add_preference(conn, subject="C001", kind="like", original_text="我平时喜欢玫瑰", explicit=True, source="消息12")
    pending = storage.add_preference(conn, subject="C001", kind="budget", original_text="预算最多1400元", explicit=False, source="消息13")
    assert explicit["status"] == "confirmed" and explicit["explicit"] is True
    assert pending["status"] == "pending" and pending["explicit"] is False
    assert {"id", "subject", "kind", "original_text", "source", "explicit", "status", "created_at", "updated_at"} <= set(explicit)
    confirmed = storage.confirm_preference(conn, pending["id"])
    assert confirmed["status"] == "confirmed"
    revoked = storage.revoke_preference(conn, pending["id"])
    assert revoked["status"] == "revoked"
    with pytest.raises(NotFoundError):
        storage.confirm_preference(conn, 9999)
    with pytest.raises(NotFoundError):
        storage.revoke_preference(conn, 9999)
    assert len(storage.list_preferences(conn, subject="C001")) == 2
    assert [item["status"] for item in storage.list_preferences(conn, subject="C001", status="confirmed")] == ["confirmed"]
    assert storage.list_preferences(conn, subject="C404") == []
    assert storage.list_preferences(conn, status="revoked")[0]["kind"] == "budget"


def test_errors_share_base_class():
    assert issubclass(NotFoundError, StorageError)
    assert issubclass(ConflictError, StorageError)
