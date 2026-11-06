"""读取小规模虚构资料；以后数据库接入从这里替换，不改变生成合同。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import CaseSpec, GenerationRequest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CATALOGS = {"brand", "products", "customers", "policies", "events"}


def load_catalog(kind: str, *, root: Path = PROJECT_ROOT) -> dict | list:
    if kind not in CATALOGS:
        raise ValueError("未知资料类型")
    return json.loads((Path(root) / "data" / "fictional" / f"{kind}.json").read_text(encoding="utf-8-sig"))


def catalog_records(catalog: dict | list) -> list[dict[str, Any]]:
    return catalog if isinstance(catalog, list) else catalog.get("records", [])


def load_cases(split: str = "dev", *, root: Path = PROJECT_ROOT) -> list[CaseSpec]:
    if split == "all":
        return load_cases("dev", root=root) + load_cases("holdout", root=root)
    if split not in {"dev", "holdout", "boundary"}:
        raise ValueError("split 须为 dev、holdout、boundary 或 all")
    path = Path(root) / "data" / "cases" / f"{split}.jsonl"
    cases = [CaseSpec.model_validate_json(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError(f"{split} 存在重复 case_id")
    if any(case.split != split for case in cases):
        raise ValueError(f"{split} 案例的 split 标记不一致")
    return cases


def load_facts(request: GenerationRequest, *, root: Path = PROJECT_ROOT) -> dict[str, Any]:
    """只取生成所需事实，评价预期与案例真值没有读取入口。"""
    brand = load_catalog("brand", root=root)
    policies = load_catalog("policies", root=root)
    products_source = load_catalog("products", root=root)
    customers_source = load_catalog("customers", root=root)
    events_source = load_catalog("events", root=root)
    products = catalog_records(products_source)
    customers = catalog_records(customers_source)
    events = catalog_records(events_source)
    unknown: list[str] = []
    selected_products = []
    if request.product_ids:
        for item_id in request.product_ids:
            matches = [item for item in products if item_id in {item.get("sku_id"), item.get("product_id")}]
            if not matches:
                unknown.append(f"未知商品或 SKU：{item_id}")
            for item in matches:
                if item not in selected_products:
                    selected_products.append(item)
    elif request.scenario in {"产品推荐", "购后关怀", "价格异议"}:
        selected_products = products
    customer = next((item for item in customers if (item.get("client_id") or item.get("customer_id") or item.get("id")) == request.client_id), None) if request.client_id else None
    if request.client_id and customer is None:
        unknown.append(f"未知客户档案：{request.client_id}")
    event = next((item for item in events if item.get("event_id", item.get("id")) == request.event_id), None) if request.event_id else None
    if request.event_id and event is None:
        unknown.append(f"未知活动：{request.event_id}")

    # 档案与当前输入分开保存，不能把新送礼需求改写为购买者长期偏好。
    refs = []
    for kind, source in [("brand", brand), ("policies", policies), ("products", products_source), ("customers", customers_source), ("events", events_source)]:
        if isinstance(source, dict):
            refs.append({"kind": kind, "source": source.get("source", "fictional"), "version": source.get("version", "unversioned")})
    for kind, items, catalog in [("product", selected_products, products_source), ("customer", [customer] if customer else [], customers_source), ("event", [event] if event else [], events_source)]:
        defaults = catalog if isinstance(catalog, dict) else {}
        for item in items:
            refs.append({"kind": kind, "id": item.get("sku_id") or item.get("client_id") or item.get("customer_id") or item.get("event_id") or item.get("id"), "source": item.get("source", defaults.get("source", "fictional")), "version": item.get("version", defaults.get("version", "unversioned"))})
    return {
        "brand": brand,
        "policies": policies,
        "products": selected_products,
        "customer_profile": customer,
        "event": event,
        "references": refs,
        "unknown_references": unknown,
    }


def contact_is_blocked(request: GenerationRequest, facts: dict[str, Any]) -> bool:
    blocked_values = {"denied", "blocked", "no", "opt_out", "拒绝", "禁止", "不允许", "禁止联系", "明确拒绝", "已退订"}
    for info in (request.client_information, facts.get("customer_profile") or {}):
        permission = info.get("contact_permission")
        if permission is False or (isinstance(permission, str) and permission.strip().lower() in blocked_values):
            return True
    return False


def required_information(request: GenerationRequest, facts: dict[str, Any]) -> list[str]:
    missing = list(facts.get("unknown_references", []))
    client = request.client_information
    has_need = bool(client.get("current_need") or request.conversation_history)
    if request.scenario == "生日与节庆" and not (request.occasion or client.get("occasion")):
        missing.append("祝福缘由（生日或具体节庆）")
    if request.scenario in {"产品推荐", "购后关怀", "价格异议"} and not has_need:
        missing.append("本次需求或客户原话")
    meaningful_client = any(value for key, value in client.items() if key not in {"contact_permission", "buyer", "recipient", "name", "customer_id"})
    if request.scenario == "沉睡唤醒" and not (meaningful_client or facts.get("customer_profile") or request.conversation_history):
        missing.append("过去互动、已知兴趣或关系背景")
    if request.scenario == "活动邀请":
        event = facts.get("event")
        if not event:
            missing.append("具体活动")
        else:
            for field in ("start_at", "timezone", "location", "content", "conditions"):
                if not event.get(field):
                    missing.append(f"活动 {field}")
    if request.scenario in {"产品推荐", "购后关怀", "价格异议"} and not facts.get("products"):
        missing.append("可核对的商品资料")
    return missing
