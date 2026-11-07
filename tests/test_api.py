"""S2 API 层离线检查：TestClient + tmp_path SQLite + 显式替身模型；零真实模型调用。

覆盖：会话创建/版本冲突、消息外部键去重、生成幂等（同键同内容返回原 ID、同键不同内容 409）、
生成成功后 GET 三稿、草稿修订 409 防覆盖、复制动作留证 copied_text、偏好确认/撤销、
settings/model 不含密钥、统一错误结构与请求 ID。
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from qixu_advisor import api, storage
from qixu_advisor.api import create_app
from qixu_advisor.models import Candidate, GenerationResult


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
    """显式替身：按调用签名 (request, run_id, case_id, *, root) 记录调用并返回预设结果；零真实模型调用。"""

    def __init__(self, result=None):
        self.result = result
        self.calls: list[tuple] = []

    def __call__(self, request, run_id, case_id, *, root=None, **kwargs):
        self.calls.append((request, run_id, case_id))
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


def test_generation_idempotency_same_key_same_content(client, monkeypatch):
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
    assert {"configured", "provider", "model", "base_url", "missing"} >= set(payload)
    text = response.text
    assert "api_key" not in text and "secret" not in text.lower()


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
