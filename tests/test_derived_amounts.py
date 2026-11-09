"""formal-v3 回归复现：推导金额（单位价/差价）不再误报，真实错误仍告警。

候选文本与输入按 formal-v3 真实案例硬编码（PRICE-101/PRICE-102/PRICE-003/REC-002），
不依赖 artifacts 路径；全部为纯程序检查，零真实模型调用。
"""

import shutil
from pathlib import Path

import pytest

from qixu_advisor.data import PROJECT_ROOT, load_facts
from qixu_advisor.generation import check_explicit_facts
from qixu_advisor.models import Candidate, GenerationRequest


@pytest.fixture
def isolated_root(tmp_path: Path) -> Path:
    shutil.copytree(PROJECT_ROOT / "data" / "fictional", tmp_path / "data" / "fictional")
    return tmp_path


def price101_request() -> GenerationRequest:
    # 真实 input 快照（holdout PRICE-101）：砚泊 30 mL 780 元与青岚 50 mL 980 元比较单位价。
    return GenerationRequest(scenario="价格异议",
        client_information={"buyer": {"address": "陈先生"}, "long_term_preferences": {"likes": ["干燥木质"], "dislikes": ["甜香"]},
            "contact_permission": "allowed", "relationship": "熟悉品牌但偏好简短沟通",
            "history": [{"type": "trial", "product_id": "YANBO", "date": "2026-09-01", "feedback": "愿意收到试香信息"}],
            "current_need": "砚泊30 mL为780元，客户觉得每毫升价格贵，问为什么小瓶划算。"},
        conversation_history=[{"role": "client", "content": "30毫升780，也不便宜吧，小瓶为什么会更划算？"}],
        product_ids=["YANBO-30", "QINGLAN-50"])


def price102_request() -> GenerationRequest:
    # 真实 input 快照（holdout PRICE-102）：预算 1400 元（客户原话）。
    return GenerationRequest(scenario="价格异议",
        client_information={"buyer": {"address": "周先生"}, "long_term_preferences": {"likes": ["柑橘", "清爽木质"], "dislikes": ["浓郁花香"]},
            "contact_permission": "allowed", "relationship": "购过青岚",
            "history": [{"type": "purchase", "sku_id": "QINGLAN-50", "date": "2026-10-30"}],
            "current_need": "想比较青岚两个容量总价，预算最多1400元，不愿超预算。", "budget_cny": 1400},
        conversation_history=[{"role": "client", "content": "100毫升看着单价低，但我这次最多花1400。"}],
        product_ids=["QINGLAN-50", "QINGLAN-100"])


def price003_request() -> GenerationRequest:
    # 真实 input 快照（dev PRICE-003）：客户原话 980/1080 均在历史中。
    return GenerationRequest(scenario="价格异议",
        client_information={"buyer": {"address": "叶女士"}, "long_term_preferences": {"likes": ["玫瑰"], "dislikes": []},
            "contact_permission": "allowed", "relationship": "购过暮光",
            "history": [{"type": "purchase", "sku_id": "MUGUANG-50", "date": "2026-10-31"}],
            "current_need": "客户称昨天顾问说暮光50 mL是980元，现标价1080元，希望兑现。"},
        conversation_history=[{"role": "client", "content": "昨天你同事跟我说暮光50 mL是980，今天怎么变1080？能按昨天说的吗？"}],
        product_ids=["MUGUANG-50"])


def rec002_request() -> GenerationRequest:
    # 真实 input 快照（dev REC-002）：青岚两规格，预算 1600。
    return GenerationRequest(scenario="价格异议",
        client_information={"buyer": {"address": "周先生"}, "long_term_preferences": {"likes": ["柑橘", "清爽木质"], "dislikes": ["浓郁花香"]},
            "contact_permission": "allowed", "relationship": "购过青岚",
            "history": [{"type": "purchase", "sku_id": "QINGLAN-50", "date": "2026-10-30"}],
            "current_need": "自己日常用，偏清爽柑橘，不要浓花香，预算1600元。", "budget_cny": 1600},
        conversation_history=[{"role": "client", "content": "主要想日常用，青岚两个容量怎么选？"}],
        product_ids=["QINGLAN-50", "QINGLAN-100"])


def test_price101_real_candidates_no_warnings(isolated_root: Path):
    """PRICE-101（formal-v3 真实候选）：每毫升 26 元（780/30）与 19.6 元（980/50）是推导单位价，不告警。"""
    request = price101_request()
    facts = load_facts(request, root=isolated_root)
    real_texts = [
        "陈先生，30 mL 780 元确实是每毫升 26 元，比青岚 50 mL 的每毫升 19.6 元高。小瓶单价高是容量决定的，不是砚泊 30 mL 更划算。两款是不同规格，我没有可用的折扣或赠品政策。砚泊是干燥木质与焚香气息，甜度低。",
        "陈先生，您说的贵我理解。砚泊 30 mL 是 780 元，折合每毫升 26 元；青岚 50 mL 是 980 元，折合每毫升 19.6 元。所以小瓶的每毫升价格其实更高，谈不上更划算。目前没有可引用的优惠，价格按商品卡来。",
        "陈先生，30 mL 780 元折合每毫升 26 元，青岚 50 mL 980 元折合每毫升 19.6 元，小瓶每毫升确实更贵。您之前到店闻过砚泊，如果还想再比较，可以到店试闻青岚，两款都是低甜度。价格和优惠我这边没有额外的，只能按商品卡报给您。",
    ]
    candidates = [Candidate(candidate_id=f"PRICE-101-C{i}", text=text) for i, text in enumerate(real_texts, 1)]
    assert check_explicit_facts(candidates, facts, request) == []


def test_price102_real_candidates_no_warnings(isolated_root: Path):
    """PRICE-102（formal-v3 真实候选）：超预算 180 元（|1580-1400|，1400 为客户原话）是推导差价，不告警。"""
    request = price102_request()
    facts = load_facts(request, root=isolated_root)
    real_texts = [
        "周先生，青岚 50 mL 是 980 元，100 mL 是 1580 元。100 mL 的单价确实低一些，但按您这次 1400 元的预算，50 mL 在范围内，100 mL 会超 180 元。目前没有可以用的优惠，我不想让您为凑单价超预算。",
        "周先生，您说得对，100 mL 折到每毫升是更划算。不过总价还是 1580 元，比您这次的上限多 180 元；50 mL 是 980 元，在预算内。两个容量的气味一样，都是柑橘与雪松，选哪个主要看您这次愿意花多少。",
        "周先生，按 1400 元的预算，青岚 50 mL 的 980 元是合适的，100 mL 的 1580 元会超。您之前买过 50 mL，如果这次想先确认再决定，可以到店试闻青岚，我把时间帮您和门店对一下。",
    ]
    candidates = [Candidate(candidate_id=f"PRICE-102-C{i}", text=text) for i, text in enumerate(real_texts, 1)]
    assert check_explicit_facts(candidates, facts, request) == []


def test_price003_real_candidates_no_warnings(isolated_root: Path):
    """PRICE-003（formal-v3 真实候选）：差价 100 元（|1080-980|，980 为客户原话）是推导差价，不告警。"""
    request = price003_request()
    facts = load_facts(request, root=isolated_root)
    real_texts = [
        "叶女士，暮光 50 mL 现在商品卡上的标价是 1080 元，人民币。您说的 980 是昨天同事口头讲的，我需要先跟门店核实这个说法，不能直接按它改价。核实清楚后我给您一个明确答复。",
        "叶女士，这件事我先说明白：暮光 50 mL 目前的标价是 1080 元，我这边没有可以按 980 元兑现的依据。昨天同事的说法我会去问清楚，是我同事讲错了，还是有别的口径，问完告诉您。",
        "叶女士，暮光 50 mL 标价 1080 元，和您昨天听到的 980 元差了 100 元，这个差额我理解您在意。昨天的口头说法我请门店同事一起核对，核对结果今天内回您。您上次买过暮光 50 mL，如果还想再闻一下再决定，也可以到店试闻。",
    ]
    candidates = [Candidate(candidate_id=f"PRICE-003-C{i}", text=text) for i, text in enumerate(real_texts, 1)]
    assert check_explicit_facts(candidates, facts, request) == []


def test_rec002_real_candidates_no_warnings(isolated_root: Path):
    """REC-002（formal-v3 真实候选）：两容量差价 600 元（|1580-980|）是推导差价，不告警。"""
    request = rec002_request()
    facts = load_facts(request, root=isolated_root)
    real_texts = [
        "周先生，青岚这两个容量价格分别是50 mL 980元、100 mL 1580元。您预算1600元，100 mL也在范围内，只是比50 mL多600元。青岚是柑橘与雪松气息、甜度低，和您平时偏清爽柑橘、不要浓花香的口味对得上。日常用的话，50 mL先看用量是否顺手，用完再续也稳妥。",
        "周先生，您10月30日买过青岚50 mL，这次两个容量怎么选，主要看您日常用得频不频繁。50 mL是980元，100 mL是1580元，都在您说的1600元预算内。青岚是柑橘与雪松气息，甜度低，和您长期偏清爽柑橘、不喜浓花香的偏好一致。要是每天用得多，100 mL更省得来回补；用得少，50 mL就够。",
        "周先生，青岚50 mL是980元，100 mL是1580元，您预算1600元，两个都能比较。您偏清爽柑橘、不要浓花香，青岚是柑橘与雪松气息、甜度低，方向是合适的。如果想先确认日常用量再定，可以来店试闻，也可以先拿50 mL用一段时间看合不合手。您平时大概多久用一次香水？我按这个帮您看哪个容量更合适。",
    ]
    candidates = [Candidate(candidate_id=f"REC-002-C{i}", text=text) for i, text in enumerate(real_texts, 1)]
    assert check_explicit_facts(candidates, facts, request) == []


def test_wrong_unit_price_still_warned(isolated_root: Path):
    """对照组：单位价写错（21 元/毫升，偏离所有 SKU 单价 0.05 以上）仍告警。"""
    request = rec002_request()
    facts = load_facts(request, root=isolated_root)
    candidate = Candidate(candidate_id="T", text="青岚50毫升折合每毫升21元。")
    warnings = check_explicit_facts([candidate], facts, request)
    assert any("请核对是品牌报价还是顾客原话" in warning for warning in warnings)
    assert any("该金额未在本次资料中出现" in warning for warning in warnings)


def test_unit_price_outside_tolerance_still_warned(isolated_root: Path):
    """对照组：单位价 19.5 元/毫升与 19.6 相差 0.1，超出 0.05 容差，仍告警。"""
    request = rec002_request()
    facts = load_facts(request, root=isolated_root)
    candidate = Candidate(candidate_id="T", text="青岚50毫升折合每毫升19.5元。")
    warnings = check_explicit_facts([candidate], facts, request)
    assert any("请核对是品牌报价还是顾客原话" in warning for warning in warnings)


def test_random_non_derived_amount_still_warned(isolated_root: Path):
    """对照组：既非事实价也非推导值的错误金额仍告警。"""
    request = price101_request()
    facts = load_facts(request, root=isolated_root)
    candidate = Candidate(candidate_id="T", text="青岚50毫升是1050元。")
    warnings = check_explicit_facts([candidate], facts, request)
    assert any("请核对是品牌报价还是顾客原话" in warning for warning in warnings)
    assert any("该金额未在本次资料中出现" in warning for warning in warnings)


def price103_request() -> GenerationRequest:
    # 真实 input 快照（holdout PRICE-103）：暮光两规格，客户问两瓶 50 mL 能否便宜。
    return GenerationRequest(scenario="价格异议",
        client_information={"buyer": {"address": "叶女士"}, "long_term_preferences": {"likes": ["玫瑰"], "dislikes": []},
            "contact_permission": "allowed", "relationship": "购过暮光",
            "history": [{"type": "purchase", "sku_id": "MUGUANG-50", "date": "2026-10-31"}],
            "current_need": "问一次买两瓶暮光能否便宜一些。"},
        conversation_history=[{"role": "client", "content": "如果我买两瓶50毫升的暮光，能少一点吗？"}],
        product_ids=["MUGUANG-50", "MUGUANG-100"])


def test_price103_formal_v5_real_candidates_no_warnings(isolated_root: Path):
    """formal-v5 PRICE-103：合计语境「两瓶/一共」与金额间隔超过 10 字符时仍识别为推导总价，不告警。"""
    request = price103_request()
    facts = load_facts(request, root=isolated_root)
    real_texts = [
        "两瓶50毫升暮光目前没有折扣，一共2160元。要是想省一点，100毫升的暮光1680元，单价更低。您按自己的用量选就好。",
        "两瓶50毫升暮光没有优惠，按标价是2160元。同款100毫升是1680元，您方便的话可以比较一下两种规格。",
        "目前两瓶50毫升暮光没有折扣，一共2160元。这个价格我这边没法再动，您要是想按更低的单价买，100毫升的暮光是1680元。您看要不要先算一下自己的用量？",
    ]
    candidates = [Candidate(candidate_id=f"PRICE-103-C{i}", text=text) for i, text in enumerate(real_texts, 1)]
    assert check_explicit_facts(candidates, facts, request) == []


def test_two_bottle_sum_without_total_context_still_warned(isolated_root: Path):
    """对照组：没有合计语境标记（无「合计/一共/N瓶」等）的两个瓶价之和仍告警。"""
    request = price103_request()
    facts = load_facts(request, root=isolated_root)
    candidate = Candidate(candidate_id="T", text="暮光50毫升1080元，两支共2160元。")
    warnings = check_explicit_facts([candidate], facts, request)
    assert any("该金额未在本次资料中出现" in warning and "2160" in warning for warning in warnings)


def price101_v9_request() -> GenerationRequest:
    # 真实 input 快照（formal-v9 PRICE-101）：青岚两规格单位价比较。
    return GenerationRequest(scenario="价格异议",
        client_information={"buyer": {"address": "贺女士"}, "long_term_preferences": {"likes": ["柑橘", "玫瑰"], "dislikes": []},
            "contact_permission": "allowed", "relationship": "SVIP 老客，会写香评",
            "history": [{"type": "trial", "product_id": "QINGLAN", "date": "2025-11-08", "feedback": "喜欢柑橘前调"},
                        {"type": "purchase", "sku_id": "MUGUANG-100", "date": "2025-12-28"}],
            "luxury_context": {"vip_tier": "SVIP"},
            "current_need": "比较青岚 100 mL 1580 元与 50 mL 980 元的单位价，问贵一点值不值"},
        conversation_history=[{"role": "client", "content": "青岚 100 毫升 1580，50 毫升 980。每毫升差多少？贵一点值不值？"}],
        product_ids=["QINGLAN-50", "QINGLAN-100"])


def test_price101_formal_v9_real_candidates_no_warnings(isolated_root: Path):
    """formal-v9 PRICE-101：每毫升 19.6/15.8 与每毫升差值 3.8、总差价 600 均为推导，不告警。"""
    request = price101_v9_request()
    facts = load_facts(request, root=isolated_root)
    real_texts = [
        "贺女士，按标价算，青岚 50 mL 是每毫升 19.6 元，100 mL 是每毫升 15.8 元，差 3.8 元。100 mL 总价高 600 元，单位价低一些。值不值主要看您用得完用不完，我这边没有额外优惠可以给到。",
        "算给您：青岚 50 mL 980 元，合每毫升 19.6 元；100 mL 1580 元，合每毫升 15.8 元。100 mL 每毫升省 3.8 元，但一次多付 600 元。您平时用量不算大，可以先按 50 mL 考虑。",
        "贺女士，两个规格的单位价我算了下：50 mL 每毫升 19.6 元，100 mL 每毫升 15.8 元。差价来自容量，香是一样的。您要是想再闻一次确认，我可以帮您登记到店试香意向，由门店跟您约时间。",
    ]
    candidates = [Candidate(candidate_id=f"PRICE-101-C{i}", text=text) for i, text in enumerate(real_texts, 1)]
    assert check_explicit_facts(candidates, facts, request) == []


def test_wrong_unit_price_still_warned_v9(isolated_root: Path):
    """对照组：错误单位价（每毫升 21 元，不是任何 SKU 单位价或单位价差）仍告警。"""
    request = price101_v9_request()
    facts = load_facts(request, root=isolated_root)
    candidate = Candidate(candidate_id="T", text="青岚 50 mL 是每毫升 21 元。")
    warnings = check_explicit_facts([candidate], facts, request)
    assert any("该金额未在本次资料中出现" in warning and "21" in warning for warning in warnings)


def rec106_v9_request() -> GenerationRequest:
    # 真实 input 快照（formal-v9 REC-106）：为商务伙伴选木质调。
    return GenerationRequest(scenario="产品推荐",
        client_information={"buyer": {"address": "周先生"}, "long_term_preferences": {"likes": ["柑橘", "清爽木质"], "dislikes": ["浓郁花香"]},
            "contact_permission": "allowed", "relationship": "购过青岚",
            "history": [{"type": "purchase", "sku_id": "QINGLAN-50", "date": "2026-10-30"}],
            "luxury_context": {"vip_tier": "VIP", "gifting_occasions": ["商务伙伴答谢"]},
            "current_need": "为商务伙伴选购礼品；收礼人偏好木质，与购买者柑橘偏好不同，不套用购买者偏好",
            "recipient": {"relationship": "商务伙伴", "likes": ["木质"]}},
        conversation_history=[{"role": "client", "content": "给一位商务伙伴挑礼物，他平时用木质调。别按我的喜好来，我喜欢柑橘。"}],
        product_ids=["YANBO-30", "MUGUANG-50", "MUGUANG-100"])


def test_rec106_formal_v9_real_candidates_no_warnings(isolated_root: Path):
    """formal-v9 REC-106：无连接词的共享容量列表「50 mL 和 100 mL，1080 元和 1680 元」按顺序配对，不告警。"""
    request = rec106_v9_request()
    facts = load_facts(request, root=isolated_root)
    real_texts = [
        "收到。按您说的，先不看柑橘，只看木质这一路。这次能比较的是砚泊 30 mL，干燥木质和焚香气息，780 元；还有暮光 50 mL 和 100 mL，玫瑰与柔和木质，1080 元和 1680 元。若只想贴着他的木质偏好，砚泊更直接；暮光带一点玫瑰，商务场合也稳，但要看他对花香接不接受。",
        "明白，送礼按收礼人的习惯来。木质这条线上，砚泊 30 mL 是干燥木质与焚香，780 元；暮光有 50 mL 和 100 mL，1080 元和 1680 元，是玫瑰与柔和木质。您平时不喜欢浓郁花香，这点不影响这次挑选，不过收礼人对花香的接受度我不清楚，不好替他判断。要不您先来店里闻一下这两支，再定送哪支？",
        "好，那就不套您的偏好。可以先把砚泊和暮光作为两个方向：砚泊 30 mL，干燥木质与焚香，780 元；暮光 50 mL 1080 元、100 mL 1680 元，玫瑰与柔和木质。您方便的话，我把这两支的气味描述发您，或者帮您登记到店试香意向，由门店和您确认时间。",
    ]
    candidates = [Candidate(candidate_id=f"REC-106-C{i}", text=text) for i, text in enumerate(real_texts, 1)]
    assert check_explicit_facts(candidates, facts, request) == []


def test_shared_capacity_list_with_reversed_amounts_still_warned(isolated_root: Path):
    """对照组：无连接词的共享容量列表金额写反（50 mL→1680、100 mL→1080）仍逐对告警。"""
    request = rec106_v9_request()
    facts = load_facts(request, root=isolated_root)
    candidate = Candidate(candidate_id="T", text="暮光有 50 mL 和 100 mL，1680 元和 1080 元。")
    warnings = check_explicit_facts([candidate], facts, request)
    assert any("50 mL" in warning and "请核对是品牌报价还是顾客原话" in warning for warning in warnings)
    assert any("100 mL" in warning and "请核对是品牌报价还是顾客原话" in warning for warning in warnings)
