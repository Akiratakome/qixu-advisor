"""S2 API 层离线检查：TestClient + tmp_path SQLite + 显式替身模型；零真实模型调用。

覆盖：会话创建/版本冲突、消息外部键去重、生成幂等（同键同内容返回原 ID、同键不同内容 409）、
生成成功后 GET 三稿、草稿修订 409 防覆盖、复制动作留证 copied_text、偏好确认/撤销、
settings/model 不含密钥、统一错误结构与请求 ID。
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from qixu_advisor import api, generation as generation_module, records as records_module, storage
from qixu_advisor.api import create_app
from qixu_advisor.models import AnalysisResult, Candidate, GenerationResult

# 模块导入时捕获真实 create_run：autouse 替身会在测试期间替换同名模块属性，
# 需要走真实建运行路径的用例用它恢复（否则自引用取到的仍是替身）。
_REAL_CREATE_RUN = records_module.create_run


@pytest.fixture
def app(tmp_path: Path):
    return create_app(tmp_path / "api.sqlite3")


@pytest.fixture
def client(app):
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "api.sqlite3"


@pytest.fixture(autouse=True)
def stub_create_run(monkeypatch):
    """所有用例默认替身 records.create_run，避免测试写入真实 artifacts/runs。"""
    calls: list[dict] = []

    def fake_create_run(case_ids, *, root=None, run_id=None, execution_mode="real", parent_run_id=None, config=None):
        calls.append({"case_ids": list(case_ids), "run_id": run_id, "execution_mode": execution_mode, "root": root, "config": config})
        return run_id or "stub-run"

    monkeypatch.setattr(api.records, "create_run", fake_create_run)
    return calls


def success_result(request=None, run_id="stub-run", case_id="stub-case") -> GenerationResult:
    return GenerationResult(
        run_id=run_id,
        case_id=case_id,
        status="success",
        candidates=[
            Candidate(candidate_id=f"{case_id}-C1", text="第一条候选：青岚 50mL 980 元，柑橘雪松清新自然。"),
            Candidate(candidate_id=f"{case_id}-C2", text="第二条候选：暮光 50mL 1080 元，玫瑰柔和适合送礼。"),
            Candidate(candidate_id=f"{case_id}-C3", text="第三条候选：雨白 50mL 1180 元，茶香鸢尾安静有记忆点。"),
        ],
    )


def needs_input_result(request=None, run_id="stub-run", case_id="stub-case") -> GenerationResult:
    return GenerationResult(run_id=run_id, case_id=case_id, status="needs_input", missing_fields=["本次需求或客户原话"])


def blocked_result(request=None, run_id="stub-run", case_id="stub-case") -> GenerationResult:
    return GenerationResult(run_id=run_id, case_id=case_id, status="contact_blocked", error="资料明确禁止联系，本次未调用模型")


class FakeGenerator:
    """显式替身：按调用签名 (request, run_id, case_id, *, root, config) 记录调用并返回预设结果；零真实模型调用。"""

    def __init__(self, result=None):
        self.result = result
        self.calls: list[tuple] = []
        self.kwargs_list: list[dict] = []

    def __call__(self, request, run_id, case_id, *, root=None, **kwargs):
        self.calls.append((request, run_id, case_id))
        self.kwargs_list.append(dict(kwargs))
        result = self.result(request, run_id, case_id) if callable(self.result) else self.result
        if isinstance(result, BaseException):
            raise result
        return result


def make_conversation(client, **overrides) -> dict:
    body = {"scenario": "产品推荐", "current_need": "为朋友选香"}
    body.update(overrides)
    response = client.post("/api/v1/conversations", json=body)
    assert response.status_code == 201, response.text
    return response.json()


# ---------- 会话与消息 ----------


def test_conversation_create_patch_version_conflict(client):
    created = make_conversation(client)
    assert created["conversation_id"] and created["version"] == 1 and created["scenario"] == "产品推荐"

    response = client.patch(f"/api/v1/conversations/{created['conversation_id']}", json={"expected_version": 1, "current_need": "为朋友选柑橘香"})
    assert response.status_code == 200
    assert response.json()["version"] == 2 and response.json()["current_need"] == "为朋友选柑橘香"

    stale = client.patch(f"/api/v1/conversations/{created['conversation_id']}", json={"expected_version": 1, "current_need": "覆盖写入"})
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "conflict"

    detail = client.get(f"/api/v1/conversations/{created['conversation_id']}")
    assert detail.status_code == 200
    assert detail.json()["messages"] == [] and detail.json()["version"] == 2

    assert client.get("/api/v1/conversations").json()[0]["conversation_id"] == created["conversation_id"]
    assert client.get("/api/v1/conversations/C404").status_code == 404


def test_patch_conversation_updates_settings_and_product_ids(client):
    """生产联调修复：settings/product_ids 必须映射到 settings_json/product_ids_json 列，
    序列化后落库；再次 GET 能读回相同值；expected_version 不符仍 409。"""
    conversation = make_conversation(client)
    url = f"/api/v1/conversations/{conversation['conversation_id']}"
    settings = {"output_language": "en", "tone": "warm"}
    product_ids = ["QINGLAN-50", "YUBAI-50"]

    patched = client.patch(
        url,
        json={
            "expected_version": 1,
            "settings": settings,
            "product_ids": product_ids,
            "current_need": "为妹妹选柑橘香",
        },
    )
    assert patched.status_code == 200, patched.text
    payload = patched.json()
    # settings 以整份字典落库（含非 None 默认项，与 create 一致），断言更新项已生效。
    assert payload["settings"]["output_language"] == "en"
    assert payload["settings"]["tone"] == "warm"
    assert payload["product_ids"] == product_ids
    assert payload["current_need"] == "为妹妹选柑橘香"
    assert payload["version"] == 2

    fetched = client.get(url)
    assert fetched.status_code == 200
    assert fetched.json()["settings"] == payload["settings"]
    assert fetched.json()["product_ids"] == product_ids
    assert fetched.json()["version"] == 2

    conflict = client.patch(url, json={"expected_version": 1, "settings": {"tone": "direct"}})
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "conflict"


def test_patch_conversation_settings_recipient_roundtrip(client):
    """WritingSettings.recipient（临时收礼人）可写可读：PATCH 落库、GET 读回。"""
    conversation = make_conversation(client)
    url = f"/api/v1/conversations/{conversation['conversation_id']}"

    patched = client.patch(url, json={"expected_version": 1, "settings": {"recipient": "妹妹"}})
    assert patched.status_code == 200, patched.text
    assert patched.json()["settings"]["recipient"] == "妹妹"

    fetched = client.get(url)
    assert fetched.status_code == 200
    assert fetched.json()["settings"]["recipient"] == "妹妹"

    created = client.post("/api/v1/conversations", json={"scenario": "产品推荐", "settings": {"recipient": "朋友"}})
    assert created.status_code == 201, created.text
    assert created.json()["settings"]["recipient"] == "朋友"


def test_generation_snapshot_includes_recipient(client, monkeypatch):
    """生成快照的 client_information.recipient 来自会话 settings.recipient。"""
    fake = FakeGenerator(result=success_result)
    monkeypatch.setattr(api, "generate", fake)
    conversation = make_conversation(client)
    url = f"/api/v1/conversations/{conversation['conversation_id']}"

    patched = client.patch(url, json={"expected_version": 1, "settings": {"recipient": "送给妹妹"}})
    assert patched.status_code == 200, patched.text

    response = client.post(
        f"{url}/generations",
        json={"expected_version": 2},
        headers={"Idempotency-Key": "key-1"},
    )
    assert response.status_code == 200, response.text
    assert len(fake.calls) == 1
    request = fake.calls[0][0]
    assert request.client_information.get("recipient") == "送给妹妹"


def test_message_external_key_dedupe(client):
    conversation = make_conversation(client, scenario="价格异议")
    url = f"/api/v1/conversations/{conversation['conversation_id']}/messages"
    first = client.post(url, json={"role": "client", "content": "1180元有点贵。", "source": "wechat", "external_id": "ext-1"})
    assert first.status_code == 201, first.text
    assert first.json()["conversation_version"] == 2

    replay = client.post(url, json={"role": "client", "content": "重放同一条", "source": "wechat", "external_id": "ext-1"})
    assert replay.status_code == 200, replay.text
    assert replay.json()["message_id"] == first.json()["message_id"]
    assert replay.json()["conversation_version"] == 2

    other_source = client.post(url, json={"role": "client", "content": "另一渠道", "source": "workbench", "external_id": "ext-1"})
    assert other_source.status_code == 201

    invalid_role = client.post(url, json={"role": "system", "content": "非法角色", "source": "manual"})
    assert invalid_role.status_code == 422
    assert invalid_role.json()["error"]["code"] == "validation_error"


# ---------- 生成 ----------


def test_generation_idempotency_same_key_same_content(client, monkeypatch, stub_create_run):
    fake = FakeGenerator(result=success_result)
    monkeypatch.setattr(api, "generate", fake)
    conversation = make_conversation(client)
    url = f"/api/v1/conversations/{conversation['conversation_id']}/generations"
    body = {"expected_version": 1}

    first = client.post(url, json=body, headers={"Idempotency-Key": "key-1"})
    assert first.status_code == 200, first.text
    payload = first.json()
    assert payload["task_status"] == "completed" and payload["business_status"] == "success"
    assert payload["snapshot_version"] == 1 and payload["generation_id"]
    assert len(payload["drafts"]) == 3
    assert payload["run_id"] and payload["case_id"]

    replay = client.post(url, json=body, headers={"Idempotency-Key": "key-1"})
    assert replay.status_code == 200, replay.text
    assert replay.json()["generation_id"] == payload["generation_id"]

    different = client.post(url, json={"expected_version": 1, "settings": {"tone": "warm"}}, headers={"Idempotency-Key": "key-1"})
    assert different.status_code == 409
    assert different.json()["error"]["code"] == "conflict"

    assert len(fake.calls) == 1
    # create_run 在 generate 之前被调用一次（重放与 409 不重复创建运行）：
    # 参数含 run_id/case_id 且 execution_mode=real，config 与传入 generate 的一致。
    assert len(stub_create_run) == 1
    create_run_call = stub_create_run[0]
    assert create_run_call["execution_mode"] == "real"
    assert create_run_call["run_id"] == payload["run_id"]
    assert create_run_call["run_id"].startswith("web-")
    assert create_run_call["case_ids"] == [payload["case_id"]]
    assert create_run_call["config"] is not None
    assert create_run_call["config"].model == fake.kwargs_list[0]["config"].model


def test_generation_new_key_creates_new_task(client, monkeypatch):
    fake = FakeGenerator(result=success_result)
    monkeypatch.setattr(api, "generate", fake)
    conversation = make_conversation(client)
    url = f"/api/v1/conversations/{conversation['conversation_id']}/generations"
    first = client.post(url, json={"expected_version": 1}, headers={"Idempotency-Key": "key-1"}).json()
    second = client.post(url, json={"expected_version": 1}, headers={"Idempotency-Key": "key-2"}).json()
    assert second["generation_id"] != first["generation_id"]
    assert len(fake.calls) == 2


def test_generation_idempotency_key_in_body(client, monkeypatch):
    fake = FakeGenerator(result=success_result)
    monkeypatch.setattr(api, "generate", fake)
    conversation = make_conversation(client)
    url = f"/api/v1/conversations/{conversation['conversation_id']}/generations"
    response = client.post(url, json={"expected_version": 1, "idempotency_key": "key-body"})
    assert response.status_code == 200, response.text


def test_generation_version_conflict_does_not_call_model(client, monkeypatch):
    fake = FakeGenerator(result=success_result)
    monkeypatch.setattr(api, "generate", fake)
    conversation = make_conversation(client)
    client.patch(f"/api/v1/conversations/{conversation['conversation_id']}", json={"expected_version": 1, "current_need": "改需求"})
    response = client.post(
        f"/api/v1/conversations/{conversation['conversation_id']}/generations",
        json={"expected_version": 1},
        headers={"Idempotency-Key": "key-1"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"
    assert fake.calls == []


def test_generation_missing_key_is_422(client, monkeypatch):
    fake = FakeGenerator(result=success_result)
    monkeypatch.setattr(api, "generate", fake)
    conversation = make_conversation(client)
    response = client.post(f"/api/v1/conversations/{conversation['conversation_id']}/generations", json={"expected_version": 1})
    assert response.status_code == 422
    assert fake.calls == []


def test_generation_needs_input_no_drafts(client, monkeypatch):
    fake = FakeGenerator(result=needs_input_result)
    monkeypatch.setattr(api, "generate", fake)
    conversation = make_conversation(client)
    response = client.post(
        f"/api/v1/conversations/{conversation['conversation_id']}/generations",
        json={"expected_version": 1},
        headers={"Idempotency-Key": "key-1"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["business_status"] == "needs_input"
    assert payload["missing_fields"] == ["本次需求或客户原话"]
    assert payload["drafts"] == []
    assert len(fake.calls) == 1


def test_generation_contact_blocked_passthrough(client, monkeypatch):
    fake = FakeGenerator(result=blocked_result)
    monkeypatch.setattr(api, "generate", fake)
    conversation = make_conversation(client)
    response = client.post(
        f"/api/v1/conversations/{conversation['conversation_id']}/generations",
        json={"expected_version": 1},
        headers={"Idempotency-Key": "key-1"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["business_status"] == "contact_blocked"


def test_generation_without_scenario_is_422(client, monkeypatch):
    fake = FakeGenerator(result=success_result)
    monkeypatch.setattr(api, "generate", fake)
    conversation = make_conversation(client, scenario=None, current_need=None)
    response = client.post(
        f"/api/v1/conversations/{conversation['conversation_id']}/generations",
        json={"expected_version": 1},
        headers={"Idempotency-Key": "key-1"},
    )
    assert response.status_code == 422
    assert fake.calls == []


def test_generation_create_run_failure_marks_interrupted(client, monkeypatch, db_path):
    """create_run 抛错时端点 500，且 generation 占位行被标 interrupted，不残留 running。"""
    fake = FakeGenerator(result=success_result)
    monkeypatch.setattr(api, "generate", fake)

    def failing_create_run(case_ids, *, root=None, run_id=None, execution_mode="real", parent_run_id=None, config=None):
        raise OSError("运行目录不可写")

    monkeypatch.setattr(api.records, "create_run", failing_create_run)
    conversation = make_conversation(client)
    response = client.post(
        f"/api/v1/conversations/{conversation['conversation_id']}/generations",
        json={"expected_version": 1},
        headers={"Idempotency-Key": "key-1"},
    )
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal"
    assert body["request_id"]
    assert "Traceback" not in response.text
    assert fake.calls == []  # create_run 失败时不调用 generate

    with storage.connect_db(db_path) as conn:
        rows = [dict(row) for row in conn.execute("SELECT status FROM generations").fetchall()]
    assert rows
    assert all(row["status"] != "running" for row in rows)
    assert any(row["status"] == "interrupted" for row in rows)


def test_get_generation_returns_three_drafts(client, monkeypatch):
    fake = FakeGenerator(result=success_result)
    monkeypatch.setattr(api, "generate", fake)
    conversation = make_conversation(client)
    created = client.post(
        f"/api/v1/conversations/{conversation['conversation_id']}/generations",
        json={"expected_version": 1},
        headers={"Idempotency-Key": "key-1"},
    ).json()

    fetched = client.get(f"/api/v1/generations/{created['generation_id']}")
    assert fetched.status_code == 200, fetched.text
    payload = fetched.json()
    assert payload["generation_id"] == created["generation_id"]
    assert payload["snapshot_version"] == 1
    assert len(payload["drafts"]) == 3
    assert [draft["revision"] for draft in payload["drafts"]] == [1, 1, 1]
    assert {draft["text"] for draft in payload["drafts"]} == {draft["text"] for draft in created["drafts"]}

    assert client.get("/api/v1/generations/missing").status_code == 404


def test_generation_busy_returns_429(client, monkeypatch, db_path):
    fake = FakeGenerator(result=success_result)
    monkeypatch.setattr(api, "generate", fake)
    conversation = make_conversation(client)
    with storage.connect_db(db_path) as conn:
        storage.create_generation(conn, conversation["conversation_id"], "stale-key", "{}", expected_version=1)
    response = client.post(
        f"/api/v1/conversations/{conversation['conversation_id']}/generations",
        json={"expected_version": 1},
        headers={"Idempotency-Key": "fresh-key"},
    )
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "busy"
    assert fake.calls == []


def test_running_generation_marked_interrupted_on_startup(client, monkeypatch, db_path):
    fake = FakeGenerator(result=success_result)
    monkeypatch.setattr(api, "generate", fake)
    conversation = make_conversation(client)
    with storage.connect_db(db_path) as conn:
        generation = storage.create_generation(conn, conversation["conversation_id"], "stale-key", "{}", expected_version=1)
        generation_id = generation["id"]
    restarted = create_app(db_path)
    with TestClient(restarted, raise_server_exceptions=False) as restarted_client:
        fetched = restarted_client.get(f"/api/v1/generations/{generation_id}")
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["task_status"] == "interrupted"


# ---------- 草稿 ----------


def _make_draft(client, monkeypatch):
    fake = FakeGenerator(result=success_result)
    monkeypatch.setattr(api, "generate", fake)
    conversation = make_conversation(client)
    created = client.post(
        f"/api/v1/conversations/{conversation['conversation_id']}/generations",
        json={"expected_version": 1},
        headers={"Idempotency-Key": "key-1"},
    ).json()
    return created["drafts"][0]


def test_draft_patch_revision_conflict_409(client, monkeypatch):
    draft = _make_draft(client, monkeypatch)
    assert draft["revision"] == 1 and draft["source"] == "machine"

    stale = client.patch(f"/api/v1/drafts/{draft['draft_id']}", json={"text": "编辑稿", "expected_revision": 7})
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "conflict"

    edited = client.patch(f"/api/v1/drafts/{draft['draft_id']}", json={"text": "编辑后正文", "expected_revision": 1})
    assert edited.status_code == 200, edited.text
    assert edited.json()["revision"] == 2 and edited.json()["source"] == "edited"
    assert edited.json()["draft_id"] == draft["draft_id"]

    overwrite = client.patch(f"/api/v1/drafts/{draft['draft_id']}", json={"text": "旧版本覆盖", "expected_revision": 1})
    assert overwrite.status_code == 409

    missing = client.patch("/api/v1/drafts/999999", json={"text": "不存在", "expected_revision": 1})
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"

    generated = client.get(f"/api/v1/generations/{draft['generation_id']}").json()
    updated = [item for item in generated["drafts"] if item["draft_id"] == draft["draft_id"]][0]
    assert updated["revision"] == 2 and updated["text"] == "编辑后正文"


def test_draft_copied_action_keeps_evidence(client, monkeypatch):
    draft = _make_draft(client, monkeypatch)
    edited = client.patch(f"/api/v1/drafts/{draft['draft_id']}", json={"text": "编辑后正文", "expected_revision": 1}).json()
    assert edited["revision"] == 2

    copied = client.post(
        f"/api/v1/drafts/{draft['draft_id']}/actions",
        json={"action": "copied", "copied_text": "复制时的实际文本", "base_revision": 2},
    )
    assert copied.status_code == 201, copied.text
    assert copied.json()["action"] == "copied"
    assert copied.json()["copied_text"] == "复制时的实际文本"

    no_text = client.post(f"/api/v1/drafts/{draft['draft_id']}/actions", json={"action": "copied", "base_revision": 2})
    assert no_text.status_code == 422
    no_text_fields = no_text.json()["error"]["fields"]
    assert any("copied_text" in str(message) for message in no_text_fields.values())

    no_base = client.post(f"/api/v1/drafts/{draft['draft_id']}/actions", json={"action": "copied", "copied_text": "文本"})
    assert no_base.status_code == 422

    unknown_revision = client.post(
        f"/api/v1/drafts/{draft['draft_id']}/actions", json={"action": "copied", "copied_text": "文本", "base_revision": 99}
    )
    assert unknown_revision.status_code == 404

    selected = client.post(f"/api/v1/drafts/{draft['draft_id']}/actions", json={"action": "selected"})
    assert selected.status_code == 201 and selected.json()["action"] == "selected"

    discarded = client.post(f"/api/v1/drafts/{draft['draft_id']}/actions", json={"action": "discarded"})
    assert discarded.status_code == 201

    invalid = client.post(f"/api/v1/drafts/{draft['draft_id']}/actions", json={"action": "sent"})
    assert invalid.status_code == 422


# ---------- 偏好 ----------


def test_preferences_confirm_and_revoke(client):
    created = client.post("/api/v1/customers", json={"client_id": "C001", "display_name": "林女士"})
    assert created.status_code == 201, created.text

    explicit = client.post(
        "/api/v1/customers/C001/preferences",
        json={"kind": "like", "original_text": "我平时喜欢玫瑰", "source": "消息12", "explicit": True},
    )
    assert explicit.status_code == 201 and explicit.json()["status"] == "confirmed"

    inferred = client.post(
        "/api/v1/customers/C001/preferences",
        json={"kind": "budget", "original_text": "预算最多1400元", "source": "消息13", "explicit": False},
    )
    assert inferred.status_code == 201 and inferred.json()["status"] == "pending"

    listed = client.get("/api/v1/customers/C001/preferences")
    assert listed.status_code == 200
    assert [item["subject"] for item in listed.json()] == ["C001", "C001"]
    assert [item["status"] for item in listed.json()] == ["confirmed", "pending"]

    confirmed = client.patch(f"/api/v1/preferences/{inferred.json()['preference_id']}", json={"action": "confirm"})
    assert confirmed.status_code == 200 and confirmed.json()["status"] == "confirmed"

    revoked = client.patch(f"/api/v1/preferences/{inferred.json()['preference_id']}", json={"action": "revoke"})
    assert revoked.status_code == 200 and revoked.json()["status"] == "revoked"

    assert client.patch("/api/v1/preferences/9999", json={"action": "confirm"}).status_code == 404
    assert client.get("/api/v1/customers/C404/preferences").status_code == 404


# ---------- 目录、设置与错误结构 ----------


def test_catalog_returns_name_spec_price_description_source(client):
    response = client.get("/api/v1/catalog")
    assert response.status_code == 200, response.text
    items = response.json()
    assert len(items) == 6
    first = items[0]
    for key in ("sku_id", "product_id", "name", "volume_ml", "price_cny", "description", "source"):
        assert key in first, key
    filtered = client.get("/api/v1/catalog", params={"sku_id": "QINGLAN-50"})
    assert filtered.status_code == 200
    assert len(filtered.json()) == 1 and filtered.json()[0]["name"] == "青岚"


def test_settings_model_has_no_secret(client):
    response = client.get("/api/v1/settings/model")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "configured" in payload
    assert {"configured", "provider", "model", "base_url", "missing"} <= set(payload)
    text = response.text
    # 状态字段名 api_key_set 允许出现；绝不返回密钥值或完整密钥字段。
    assert '"api_key":' not in text and "secret" not in text.lower() and "sk-" not in text.lower()


# ---------- 运行时模型配置 ----------


def test_put_then_get_model_settings_runtime(client):
    put = client.put(
        "/api/v1/settings/model",
        json={
            "provider": "deepseek",
            "base_url": "https://api.example.com",
            "model": "custom-model",
            "api_key": "sk-test-123",
            "temperature": 0.5,
        },
    )
    assert put.status_code == 200, put.text
    payload = put.json()
    assert payload["source"] == "runtime"
    assert payload["api_key_set"] is True
    assert payload["configured"] is True
    assert payload["model"] == "custom-model"
    assert payload["base_url"] == "https://api.example.com"
    assert payload["provider"] == "deepseek"
    assert payload["missing"] == []
    assert "sk-test-123" not in put.text

    fetched = client.get("/api/v1/settings/model")
    assert fetched.status_code == 200, fetched.text
    assert fetched.json() == payload
    assert "sk-test-123" not in fetched.text


def test_put_model_settings_validation_422(client):
    bad_url = client.put("/api/v1/settings/model", json={"base_url": "not-a-url"})
    assert bad_url.status_code == 422
    assert bad_url.json()["error"]["code"] == "validation_error"
    assert "base_url" in bad_url.json()["error"]["fields"]

    bad_temperature = client.put("/api/v1/settings/model", json={"temperature": 3.5})
    assert bad_temperature.status_code == 422
    assert "temperature" in bad_temperature.json()["error"]["fields"]

    unknown_field = client.put("/api/v1/settings/model", json={"secret_extra": "x"})
    assert unknown_field.status_code == 422


def test_generation_uses_runtime_config(client, monkeypatch):
    fake = FakeGenerator(result=success_result)
    monkeypatch.setattr(api, "generate", fake)
    put = client.put(
        "/api/v1/settings/model",
        json={
            "base_url": "https://runtime.example.com",
            "model": "runtime-model",
            "api_key": "sk-runtime-1",
            "temperature": 0.3,
        },
    )
    assert put.status_code == 200, put.text
    assert put.json()["source"] == "runtime"

    conversation = make_conversation(client)
    response = client.post(
        f"/api/v1/conversations/{conversation['conversation_id']}/generations",
        json={"expected_version": 1},
        headers={"Idempotency-Key": "key-1"},
    )
    assert response.status_code == 200, response.text
    assert len(fake.calls) == 1
    config = fake.kwargs_list[0]["config"]
    assert config.model == "runtime-model"
    assert config.base_url == "https://runtime.example.com"
    assert config.api_key.get_secret_value() == "sk-runtime-1"
    assert config.temperature == 0.3


def test_clear_api_key_falls_back_to_env(client, monkeypatch):
    monkeypatch.setenv("QIXU_MODEL", "env-test-model")
    put_runtime = client.put("/api/v1/settings/model", json={"model": "runtime-model", "api_key": "sk-runtime-1"})
    assert put_runtime.status_code == 200, put_runtime.text
    assert put_runtime.json()["source"] == "runtime"

    cleared = client.put("/api/v1/settings/model", json={"api_key": ""})
    assert cleared.status_code == 200, cleared.text
    payload = cleared.json()
    assert payload["source"] == "env"
    assert payload["model"] == "env-test-model"
    assert "sk-runtime-1" not in cleared.text

    fetched = client.get("/api/v1/settings/model")
    assert fetched.json()["source"] == "env"
    assert fetched.json()["model"] == "env-test-model"


def test_generation_runtime_config_aligned_in_manifest(tmp_path, monkeypatch):
    """运行时配置下真实 create_run 建清单后，manifest.model_config 必须对齐本次实际配置，
    否则 begin_case 的「模型参数在运行创建后不变」守卫会 500。"""
    fake = FakeGenerator(result=success_result)
    monkeypatch.setattr(api, "generate", fake)
    monkeypatch.setattr(api.records, "create_run", _REAL_CREATE_RUN)  # 覆盖 autouse 替身，走真实建运行
    root = tmp_path / "root"
    (root / "src" / "qixu_advisor" / "prompts").mkdir(parents=True)
    (root / "data" / "fictional").mkdir(parents=True)
    application = create_app(root / "api.sqlite3", root=root)
    with TestClient(application, raise_server_exceptions=False) as client:
        put = client.put(
            "/api/v1/settings/model",
            json={"model": "runtime-model", "base_url": "https://runtime.example.com", "api_key": "sk-runtime-1"},
        )
        assert put.status_code == 200, put.text
        conversation = make_conversation(client)
        response = client.post(
            f"/api/v1/conversations/{conversation['conversation_id']}/generations",
            json={"expected_version": 1},
            headers={"Idempotency-Key": "key-1"},
        )
        assert response.status_code == 200, response.text
        run_id = response.json()["run_id"]
        manifest = json.loads((root / "artifacts" / "runs" / run_id / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["model_config"]["model"] == "runtime-model"
        assert manifest["model_config"]["base_url"] == "https://runtime.example.com"
        assert "api_key" not in json.dumps(manifest["model_config"])
        assert fake.kwargs_list[0]["config"].model == "runtime-model"
        assert fake.kwargs_list[0]["config"].api_key.get_secret_value() == "sk-runtime-1"


# ---------- 冷启动默认与示例客户 ----------


def test_generation_cold_start_birthday_occasion_default(client, monkeypatch, db_path):
    """无消息的生日会话缺 occasion：generate 收到默认缘由，payload_json 记默认标记，响应体不暴露。"""
    fake = FakeGenerator(result=success_result)
    monkeypatch.setattr(api, "generate", fake)
    conversation = make_conversation(client, scenario="生日与节庆", current_need=None)
    response = client.post(
        f"/api/v1/conversations/{conversation['conversation_id']}/generations",
        json={"expected_version": 1},
        headers={"Idempotency-Key": "key-1"},
    )
    assert response.status_code == 200, response.text
    assert len(fake.calls) == 1
    generated_request = fake.calls[0][0]
    assert generated_request.client_information.get("occasion") == "客户生日（默认缘由，可改）"

    with storage.connect_db(db_path) as conn:
        row = conn.execute("SELECT payload_json FROM generations").fetchone()
    payload = json.loads(row["payload_json"])
    assert payload["cold_start_defaults_applied"] is True
    assert "cold_start_defaults_applied" not in response.text


def test_generation_cold_start_complete_input_no_defaults(client, monkeypatch, db_path):
    """无消息但输入完整：不应用默认，payload 不含默认标记，原值原样传入。"""
    fake = FakeGenerator(result=success_result)
    monkeypatch.setattr(api, "generate", fake)
    conversation = make_conversation(client, scenario="生日与节庆", current_need="朋友过生日", occasion="生日")
    response = client.post(
        f"/api/v1/conversations/{conversation['conversation_id']}/generations",
        json={"expected_version": 1},
        headers={"Idempotency-Key": "key-1"},
    )
    assert response.status_code == 200, response.text
    generated_request = fake.calls[0][0]
    assert generated_request.client_information.get("occasion") == "生日"

    with storage.connect_db(db_path) as conn:
        row = conn.execute("SELECT payload_json FROM generations").fetchone()
    payload = json.loads(row["payload_json"])
    assert "cold_start_defaults_applied" not in payload


def test_generation_cold_start_event_missing_event_id_422(client, monkeypatch):
    """活动邀请缺 event_id：无默认值，422 带 fields 提示选活动，不调用模型。"""
    fake = FakeGenerator(result=success_result)
    monkeypatch.setattr(api, "generate", fake)
    conversation = make_conversation(client, scenario="活动邀请", current_need=None)
    response = client.post(
        f"/api/v1/conversations/{conversation['conversation_id']}/generations",
        json={"expected_version": 1},
        headers={"Idempotency-Key": "key-1"},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert "event_id" in body["error"]["fields"]
    assert fake.calls == []


def test_generation_cold_start_need_scenarios_422(client, monkeypatch):
    """产品推荐/价格异议缺 current_need：无默认值，422 带 fields。"""
    fake = FakeGenerator(result=success_result)
    monkeypatch.setattr(api, "generate", fake)
    for index, scenario in enumerate(("产品推荐", "价格异议"), 1):
        conversation = make_conversation(client, scenario=scenario, current_need=None)
        response = client.post(
            f"/api/v1/conversations/{conversation['conversation_id']}/generations",
            json={"expected_version": 1},
            headers={"Idempotency-Key": f"key-need-{index}"},
        )
        assert response.status_code == 422, response.text
        assert "current_need" in response.json()["error"]["fields"]
    assert fake.calls == []


def test_seed_customers_idempotent(client):
    first = client.post("/api/v1/customers/seed")
    assert first.status_code == 200, first.text
    payload = first.json()
    assert payload["total"] == 8
    assert len(payload["created"]) == 8
    assert payload["skipped"] == []

    second = client.post("/api/v1/customers/seed")
    assert second.status_code == 200, second.text
    assert second.json()["created"] == []
    assert len(second.json()["skipped"]) == 8
    assert second.json()["total"] == 8

    listed = client.get("/api/v1/customers")
    assert listed.status_code == 200
    customers = listed.json()
    assert len(customers) == 8
    by_id = {item["customer_id"]: item for item in customers}
    assert set(by_id) == set(payload["created"])
    assert "C001" in by_id
    assert by_id["C001"]["profile"]["display_name"] == "林女士"


def test_error_envelope_shape_and_request_id(client):
    missing = client.get("/api/v1/customers/NOPE")
    assert missing.status_code == 404
    body = missing.json()
    assert body["error"]["code"] == "not_found"
    assert body["error"]["message"]
    assert body["request_id"]
    assert missing.headers["x-request-id"] == body["request_id"]

    invalid = client.post("/api/v1/customers", json={"contact_permission": "maybe"})
    assert invalid.status_code == 422
    body = invalid.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["fields"] and body["request_id"]

    unknown_route = client.get("/api/v1/nope")
    assert unknown_route.status_code == 404
    assert unknown_route.json()["error"]["code"] == "not_found"
    assert unknown_route.json()["request_id"]


def test_customer_patch_version_conflict(client):
    created = client.post("/api/v1/customers", json={"display_name": "唐先生"})
    assert created.status_code == 201
    assert created.json()["version"] == 1 and created.json()["customer_id"].startswith("web-")

    updated = client.patch(f"/api/v1/customers/{created.json()['customer_id']}", json={"expected_version": 1, "relationship": "首次联系"})
    assert updated.status_code == 200
    assert updated.json()["version"] == 2 and updated.json()["profile"]["relationship"] == "首次联系"

    conflict = client.patch(f"/api/v1/customers/{created.json()['customer_id']}", json={"expected_version": 1, "display_name": "旧版本"})
    assert conflict.status_code == 409

    duplicate = client.post("/api/v1/customers", json={"client_id": created.json()["customer_id"]})
    assert duplicate.status_code == 409

    assert len(client.get("/api/v1/customers").json()) == 1


def test_preference_body_json_roundtrip():
    # 仅核对生成请求体与响应可被 JSON 序列化（无不可序列化类型混入）。
    from qixu_advisor.api_models import GenerationIn, PreferenceIn

    assert json.loads(GenerationIn(expected_version=1).model_dump_json())["expected_version"] == 1
    assert PreferenceIn(kind="like", original_text="喜欢玫瑰", source="消息1").explicit is True


# ---------- 对话分析 ----------


def test_analyze_valid_passes_history_and_client_info(client, monkeypatch):
    captured: dict = {}

    def fake_analyze(conversation_history, client_information, *, root=None, **kwargs):
        captured["conversation_history"] = conversation_history
        captured["client_information"] = client_information
        captured["calls"] = captured.get("calls", 0) + 1
        return AnalysisResult(scenario="产品推荐", current_need="为朋友选香", missing_questions=["预算大概多少？"])

    monkeypatch.setattr(generation_module, "analyze_conversation", fake_analyze)
    response = client.post(
        "/api/v1/analyze",
        json={
            "conversation_history": [
                {"role": "client", "content": "想帮朋友挑一瓶香水"},
                {"role": "advisor", "content": "您朋友偏好什么香调？"},
            ],
            "client_information": {"budget_cny": 1200},
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["scenario"] == "产品推荐"
    assert payload["current_need"] == "为朋友选香"
    assert payload["missing_questions"] == ["预算大概多少？"]
    assert payload["request_id"]
    assert captured["calls"] == 1
    assert captured["conversation_history"][0] == {"role": "client", "content": "想帮朋友挑一瓶香水"}
    assert captured["conversation_history"][1]["role"] == "advisor"
    assert captured["client_information"] == {"budget_cny": 1200}

    invalid = client.post("/api/v1/analyze", json={"conversation_history": [{"role": "system", "content": "非法角色"}]})
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"
    assert captured["calls"] == 1  # 参数校验失败不触发模型调用


def test_analyze_failure_error_body(client, monkeypatch):
    def fail_structural(conversation_history, client_information, *, root=None, **kwargs):
        raise ValueError("分析结果结构不合格：需要含 scenario（六场景之一）、current_need（非空）与 missing_questions（0–3 条非空）的 JSON；未重试")

    monkeypatch.setattr(generation_module, "analyze_conversation", fail_structural)
    structural = client.post("/api/v1/analyze", json={"conversation_history": [{"role": "client", "content": "你好"}]})
    assert structural.status_code == 502
    body = structural.json()
    assert body["error"]["code"] == "upstream_error"
    assert "结构不合格" in body["error"]["message"]
    assert body["request_id"]
    assert "Traceback" not in structural.text

    def fail_model(conversation_history, client_information, *, root=None, **kwargs):
        raise ValueError("对话分析失败：模型请求超时；没有自动重试")

    monkeypatch.setattr(generation_module, "analyze_conversation", fail_model)
    model_failure = client.post("/api/v1/analyze", json={"conversation_history": [{"role": "client", "content": "你好"}]})
    assert model_failure.status_code == 502
    assert model_failure.json()["error"]["code"] == "upstream_error"
    assert "自动重试" in model_failure.json()["error"]["message"]

    def fail_config(conversation_history, client_information, *, root=None, **kwargs):
        raise ValueError("未配置 DEEPSEEK_API_KEY；未发起真实模型请求")

    monkeypatch.setattr(generation_module, "analyze_conversation", fail_config)
    config_failure = client.post("/api/v1/analyze", json={"conversation_history": [{"role": "client", "content": "你好"}]})
    assert config_failure.status_code == 500
    assert config_failure.json()["error"]["code"] == "internal"
    assert config_failure.json()["request_id"]
    assert "Traceback" not in config_failure.text


# ---------- 静态托管（web/dist SPA） ----------


def test_static_dir_missing_keeps_api_and_json_404(tmp_path: Path):
    application = create_app(tmp_path / "no-dist.sqlite3")
    with TestClient(application, raise_server_exceptions=False) as test_client:
        root_response = test_client.get("/")
        assert root_response.status_code == 404
        assert root_response.json()["error"]["code"] == "not_found"
        assert test_client.get("/api/v1/settings/model").status_code == 200


def test_static_dir_without_index_not_mounted(tmp_path: Path):
    empty_dist = tmp_path / "empty-dist"
    empty_dist.mkdir()
    application = create_app(tmp_path / "empty.sqlite3", static_dir=empty_dist)
    with TestClient(application, raise_server_exceptions=False) as test_client:
        assert test_client.get("/").status_code == 404
        assert test_client.get("/api/v1/settings/model").status_code == 200


def test_static_dir_serves_index_spa_fallback_and_api_json_404(tmp_path: Path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html><body>QIXU 工作台</body></html>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log('qixu');", encoding="utf-8")

    application = create_app(tmp_path / "with-dist.sqlite3", static_dir=dist)
    with TestClient(application, raise_server_exceptions=False) as test_client:
        index_response = test_client.get("/")
        assert index_response.status_code == 200
        assert "QIXU 工作台" in index_response.text

        fallback = test_client.get("/app")
        assert fallback.status_code == 200
        assert "QIXU 工作台" in fallback.text

        asset = test_client.get("/assets/app.js")
        assert asset.status_code == 200
        assert "console.log" in asset.text

        unknown_api = test_client.get("/api/v1/unknown")
        assert unknown_api.status_code == 404
        assert unknown_api.json()["error"]["code"] == "not_found"
        assert unknown_api.json()["request_id"]

        assert test_client.get("/api/v1/settings/model").status_code == 200
        assert test_client.get("/api/v1/catalog").status_code == 200
