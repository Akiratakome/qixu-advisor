"""固定数据的覆盖、家族隔离与业务引用检查；不评价模型话术质量。"""

import json
from collections import Counter

from qixu_advisor.data import PROJECT_ROOT, catalog_records, load_cases, load_catalog, load_facts, required_information


def test_fixed_cases_and_reference_integrity():
    cases = load_cases("all")
    manifest = json.loads((PROJECT_ROOT / "data/cases/manifest.json").read_text(encoding="utf-8"))
    expectations = [json.loads(line) for line in (PROJECT_ROOT / "data/cases/expectations.jsonl").read_text(encoding="utf-8").splitlines() if line]
    assert len(cases) == len({c.case_id for c in cases}) == 50
    assert {c.case_id for c in cases} == {c["case_id"] for c in manifest["cases"]} == {e["case_id"] for e in expectations}
    listed = {row["case_id"]: row for row in manifest["cases"]}
    assert all(listed[c.case_id]["family_id"] == c.family_id and listed[c.case_id]["split"] == c.split for c in cases)
    expected = {"生日与节庆": (3, 5), "产品推荐": (4, 6), "购后关怀": (3, 5), "沉睡唤醒": (3, 5), "活动邀请": (3, 3), "价格异议": (4, 6)}
    counts = Counter((c.request.scenario, c.split) for c in cases)
    for scenario, (dev, holdout) in expected.items():
        assert (counts[scenario, "dev"], counts[scenario, "holdout"]) == (dev, holdout)
    dev_families = {c.family_id for c in cases if c.split == "dev"}
    assert not dev_families & {c.family_id for c in cases if c.split == "holdout"}
    assert len(manifest["diagnostic_case_ids"]) == 6
    assert set(manifest["diagnostic_case_ids"]) <= {c.case_id for c in cases if c.split == "dev"}
    assert Counter(c.request.scenario for c in cases if c.case_id in manifest["review_case_ids"]) == Counter({scenario: 2 for scenario in expected})
    for case in cases:
        facts = load_facts(case.request)
        assert required_information(case.request, facts) == [], case.case_id
        if case.request.client_id:
            assert facts["customer_profile"]["client_id"] == case.request.client_id
        assert "must_respond" not in facts and "must_not" not in facts
    assert all(1 <= len(e["must_respond"]) <= 3 and e["must_not"] for e in expectations)


def test_catalog_unknowns_and_public_source_isolation():
    products = catalog_records(load_catalog("products"))
    assert len(products) == 6 and len({p["product_id"] for p in products}) == 4
    assert len({p["sku_id"] for p in products}) == 6
    assert all(p["stock"] is None and p["longevity"] is None and p["currency"] == "CNY" for p in products)
    assert next(p for p in products if p["sku_id"] == "YUBAI-50")["sweetness"] is None
    # 未知商品/客户引用进入 unknown_references，不静默假装存在。
    from qixu_advisor.models import GenerationRequest
    facts = load_facts(GenerationRequest(scenario="产品推荐", client_information={"current_need": "想了解"}, product_ids=["NOPE-50"], client_id="C999"))
    assert "未知商品或 SKU：NOPE-50" in facts["unknown_references"]
    assert "未知客户档案：C999" in facts["unknown_references"]
    # 公开源与本地资料隔离：公开 ABCD 来源固定版本并仅登记；重写后的 50 例不再携带公开数据集标记。
    cases = {c.case_id: c for c in load_cases("all")}
    sources = [json.loads(line) for line in (PROJECT_ROOT / "data/references/sources.jsonl").read_text(encoding="utf-8").splitlines()]
    references = [s for s in sources if s.get("kind") != "style_example"]
    style_examples = [s for s in sources if s.get("kind") == "style_example"]
    assert len(references) == 4
    assert len({s["original_id"] for s in references}) == 4
    for source in references:
        case = cases[source["case_id"]]
        assert case.split == source["local_split"] == "dev"
        assert source["revision"] == "6b8700ce67c6b37b062dd7a60abc76d7ef832a97"
        assert case.source.get("dataset") != "ABCD"
        assert "original_id" not in case.source
    # 风格样本来源（生日祝福句式）：只登记、不进案例、注明许可与用途。
    assert len(style_examples) == 2
    for source in style_examples:
        assert {"name", "url", "used_for", "license_note"} <= set(source)
        assert "case_id" not in source


def test_revised_stories_and_current_purchase_contract():
    """固定已发现的具体问题；这些断言不能代替所有案例的来源语义审阅。"""
    cases = {case.case_id: case for case in load_cases("all")}
    after = cases["AFTER-105"]
    event = cases["EVENT-101"]
    assert after.request.client_id != cases["REC-001"].request.client_id
    assert event.request.client_id != cases["REC-001"].request.client_id
    assert after.request.product_ids == ["MUGUANG-50"]
    purchases = after.request.client_information["purchases"]
    assert len(purchases) == 2
    assert {item["opened"] for item in purchases} == {True, False}
    assert len({item["item_ref"] for item in purchases}) == 2
    assert sum(item["feedback"] is not None for item in purchases) == 1
    assert event.request.event_id == "EVT-WOOD"
    assert event.request.tone == "direct" and event.request.length == "short"
    # 意向、登记与门店确认分开：代登记案例的参加者出席状态未确认，活动仍要求登记并经门店确认。
    attendee_case = cases["EVENT-002"]
    assert attendee_case.request.client_information["intended_attendee"]["attendance_confirmed"] is False
    event_facts = load_facts(attendee_case.request)
    assert event_facts["event"]["booking_status"] == "未预约"
    assert "需登记意向并由门店确认" in event_facts["event"]["conditions"]
    current = cases["AFTER-103"].request.client_information
    assert load_facts(cases["AFTER-103"].request)["customer_profile"] is None
    assert current["profile_snapshot"]["as_of"] < current["purchase"]["received_date"]
    assert "未购买" not in current["relationship"]
    assert current["purchase"]["opened"] is True
