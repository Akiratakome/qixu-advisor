"""formal-v2 回归复现：check_explicit_facts 三类误报修复，并保持既有告警能力。

候选文本与输入按真实案例（PRICE-003/PRICE-103/REC-104）硬编码，不依赖 artifacts 路径；
全部为纯程序检查，不调用真实模型。
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


def price003_request() -> GenerationRequest:
    # 真实 input 快照（dev PRICE-003）：客户原话含裸数字 980/1080，product_ids 只有 MUGUANG-50。
    return GenerationRequest(scenario="价格异议",
        client_information={"buyer": {"address": "叶女士"}, "long_term_preferences": {"likes": ["玫瑰"], "dislikes": []},
            "contact_permission": "allowed", "relationship": "购过暮光",
            "history": [{"type": "purchase", "sku_id": "MUGUANG-50", "date": "2026-10-31"}],
            "current_need": "客户称昨天顾问说暮光50 mL是980元，现标价1080元，希望兑现。"},
        conversation_history=[{"role": "client", "content": "昨天你同事跟我说暮光50 mL是980，今天怎么变1080？能按昨天说的吗？"}],
        product_ids=["MUGUANG-50"])


def price103_request() -> GenerationRequest:
    # 真实 input 快照（holdout PRICE-103）：暮光两规格，客户问两瓶 50 mL 能否便宜。
    return GenerationRequest(scenario="价格异议",
        client_information={"buyer": {"address": "叶女士"}, "long_term_preferences": {"likes": ["玫瑰"], "dislikes": []},
            "contact_permission": "allowed", "relationship": "购过暮光",
            "history": [{"type": "purchase", "sku_id": "MUGUANG-50", "date": "2026-10-31"}],
            "current_need": "问一次买两瓶暮光能否便宜一些。"},
        conversation_history=[{"role": "client", "content": "如果我买两瓶50毫升的暮光，能少一点吗？"}],
        product_ids=["MUGUANG-50", "MUGUANG-100"])


def rec104_request() -> GenerationRequest:
    # 真实 input 快照（holdout REC-104）：四个商品，预算 1200，客户原话“1200以内”。
    return GenerationRequest(scenario="产品推荐",
        client_information={"buyer": {"address": "林女士"}, "long_term_preferences": {"likes": ["甜花香"], "dislikes": []},
            "contact_permission": "allowed", "relationship": "曾到店试香",
            "history": [{"type": "trial", "product_id": "MUGUANG", "date": "2026-09-10", "feedback": "喜欢柔和玫瑰气息"}],
            "current_need": "想给朋友送礼但不知道对方偏好，只知道预算1200元。",
            "recipient": {"relationship": "朋友", "likes": [], "dislikes": []}, "budget_cny": 1200},
        conversation_history=[{"role": "client", "content": "送朋友的，没问过她喜欢什么，1200以内有稳妥的吗？"}],
        product_ids=["QINGLAN-50", "MUGUANG-50", "YUBAI-50", "YANBO-30"])


def after003_request() -> GenerationRequest:
    # 真实 input 快照（dev AFTER-003）：青岚两规格，客户想换大容量。
    return GenerationRequest(scenario="购后关怀",
        client_information={"buyer": {"address": "唐先生"}, "long_term_preferences": {"likes": [], "dislikes": []},
            "contact_permission": "allowed", "relationship": "首次联系，偏好尚未知", "history": [],
            "current_need": "收到青岚12天，未拆封，想换成大容量。",
            "purchase": {"sku_id": "QINGLAN-50", "days_since_received": 12, "opened": False}},
        conversation_history=[{"role": "client", "content": "收到十二天了还没拆，我能直接换成100 mL吗？"}],
        product_ids=["QINGLAN-50", "QINGLAN-100"])


def rec002_request() -> GenerationRequest:
    # 真实 input 快照（dev REC-002）：青岚两规格，预算 1600。
    return GenerationRequest(scenario="价格异议",
        client_information={"buyer": {"address": "周先生"}, "long_term_preferences": {"likes": ["柑橘", "清爽木质"], "dislikes": ["浓郁花香"]},
            "contact_permission": "allowed", "relationship": "购过青岚",
            "history": [{"type": "purchase", "sku_id": "QINGLAN-50", "date": "2026-10-30"}],
            "current_need": "自己日常用，偏清爽柑橘，不要浓花香，预算1600元。", "budget_cny": 1600},
        conversation_history=[{"role": "client", "content": "主要想日常用，青岚两个容量怎么选？"}],
        product_ids=["QINGLAN-50", "QINGLAN-100"])


def test_price003_real_candidates_no_warnings(isolated_root: Path):
    """PRICE-003（formal-v2 真实候选）：980 为客户原话，历史裸数字进白名单后三条均不再误报。"""
    request = price003_request()
    facts = load_facts(request, root=isolated_root)
    real_texts = [
        "叶女士，您说的这个情况我看到了。暮光50 mL目前商品卡标价是1080元，昨天同事提到的980元我需要请门店核查一下，看是不是同款同规格的报价。在核查清楚之前，我不便直接按980元答复您，有结果我第一时间跟您说。",
        "叶女士，昨天那个980元的说法我记下了，不会当作没发生。先跟您核对一下：暮光50 mL现在的标价是1080元，币种是人民币。两个数字差在哪里，我请门店同事查过再回复您，您不用反复来问。",
        "叶女士，暮光50 mL现标价1080元，和您昨天听到的980元确实对不上。这个差价我这边无法直接兑现，需要请门店核查当时的报价记录。您方便的话，把昨天沟通的大致时间告诉我，我请门店同事一并核对后回复您。",
    ]
    candidates = [Candidate(candidate_id=f"PRICE-003-C{i}", text=text) for i, text in enumerate(real_texts, 1)]
    assert check_explicit_facts(candidates, facts, request) == []


def test_price003_same_amount_without_history_still_warned(isolated_root: Path):
    """对照组：同样的候选文本，若聊天没有客户原话 980，仍要告警。"""
    request = GenerationRequest(scenario="价格异议",
        client_information={"buyer": {"address": "叶女士"}, "current_need": "客户称暮光价格变了"},
        product_ids=["MUGUANG-50"])
    facts = load_facts(request, root=isolated_root)
    candidate = Candidate(candidate_id="T", text="暮光50 mL是980元。")
    warnings = check_explicit_facts([candidate], facts, request)
    assert any("请核对是品牌报价还是顾客原话" in warning for warning in warnings)


def test_price103_real_candidates_no_warnings(isolated_root: Path):
    """PRICE-103（formal-v2 真实候选）：1680 不跨配到 50 mL；两瓶合计 2160 是候选正确推算的总价。"""
    request = price103_request()
    facts = load_facts(request, root=isolated_root)
    real_texts = [
        "叶女士，两瓶50毫升的暮光目前没有折扣，价格是每瓶1080元，两瓶合计2160元。您之前买过50毫升，如果用量更稳定，也可以看看100毫升，标价1680元，单位价格会低一些。您更倾向哪种规格，我按这个帮您确认。",
        "叶女士，谢谢您直接问。两瓶50毫升暮光暂时没有优惠可申请，单瓶1080元，两瓶就是2160元。我没法给您额外让价，这点先跟您说清楚。如果您愿意，我可以把50毫升和100毫升的差别再讲细一点，方便您决定。",
        "叶女士，两瓶暮光50毫升目前按标价1080元一瓶，合计2160元，没有可用的优惠。您上次买的是50毫升，这次如果考虑100毫升，标价是1680元，总价和单位价格会不一样，可以一起比较。需要的话，我请门店同事帮您把两种规格的购买方式确认清楚。",
    ]
    candidates = [Candidate(candidate_id=f"PRICE-103-C{i}", text=text) for i, text in enumerate(real_texts, 1)]
    assert check_explicit_facts(candidates, facts, request) == []


def test_price103_adjacent_price_still_checked(isolated_root: Path):
    """对照组：紧跟容量的单点金额不匹配仍要告警。"""
    request = price103_request()
    facts = load_facts(request, root=isolated_root)
    candidate = Candidate(candidate_id="T", text="暮光50毫升是1680元，也可以看看100毫升。")
    warnings = check_explicit_facts([candidate], facts, request)
    assert any("请核对是品牌报价还是顾客原话" in warning for warning in warnings)


def test_wrong_computed_total_still_warned(isolated_root: Path):
    """对照组：合计语境下推算错误的总价（3000 不是任何目录价的小整数倍）仍要告警。"""
    request = price103_request()
    facts = load_facts(request, root=isolated_root)
    candidate = Candidate(candidate_id="T", text="暮光50毫升是1080元，两瓶合计3000元。")
    warnings = check_explicit_facts([candidate], facts, request)
    assert any("该金额未在本次资料中出现" in warning and "3000" in warning for warning in warnings)


def test_multiple_amount_without_total_context_still_warned(isolated_root: Path):
    """对照组：没有合计语境时，恰为目录价倍数的金额仍按单点报价告警。"""
    request = GenerationRequest(scenario="价格异议",
        client_information={"current_need": "想买青岚"}, product_ids=["QINGLAN-50", "QINGLAN-100"])
    facts = load_facts(request, root=isolated_root)
    candidate = Candidate(candidate_id="T", text="青岚50毫升是1960元。")
    warnings = check_explicit_facts([candidate], facts, request)
    assert any("请核对是品牌报价还是顾客原话" in warning for warning in warnings)


def test_after003_real_candidate_no_warnings(isolated_root: Path):
    """AFTER-003（formal-v2 真实候选）：「100 mL 和 50 mL 标价分别是 1580 元和 980 元」按顺序对应，不跨配。"""
    request = after003_request()
    facts = load_facts(request, root=isolated_root)
    real_text = "唐先生，青岚 100 mL 和 50 mL 的香气一样，标价分别是 1580 元和 980 元，都是人民币。您还没拆封，换容量的事需要门店按订单核查后回复。方便的话，请把购买日期和订单凭证发我，我请门店同事与您对接。"
    candidate = Candidate(candidate_id="AFTER-003-C3", text=real_text)
    assert check_explicit_facts([candidate], facts, request) == []


def test_rec002_real_candidate_no_warnings(isolated_root: Path):
    """REC-002（formal-v2 真实候选）：「50 mL和100 mL，标价分别是980元和1580元」按顺序对应，不跨配。"""
    request = rec002_request()
    facts = load_facts(request, root=isolated_root)
    real_text = "周先生，青岚这次可比较的是50 mL和100 mL，标价分别是980元和1580元，都在您说的1600元预算内。您偏好清爽柑橘、不喜浓花香，青岚是柑橘与雪松气息、甜度低，方向比较贴近。日常用的话，50 mL轻便、100 mL更耐用，看您使用频率来定就好。"
    candidate = Candidate(candidate_id="REC-002-C1", text=real_text)
    assert check_explicit_facts([candidate], facts, request) == []


def test_list_form_with_reversed_prices_still_warned(isolated_root: Path):
    """对照组：「分别是」按顺序对应后，两个价格都写反时两条容量都要告警。"""
    request = rec002_request()
    facts = load_facts(request, root=isolated_root)
    candidate = Candidate(candidate_id="T", text="青岚50毫升和100毫升标价分别是1580元和980元。")
    warnings = check_explicit_facts([candidate], facts, request)
    assert any("50 mL" in warning and "请核对是品牌报价还是顾客原话" in warning for warning in warnings)
    assert any("100 mL" in warning and "请核对是品牌报价还是顾客原话" in warning for warning in warnings)


def test_rec104_real_candidates_no_warnings(isolated_root: Path):
    """REC-104（formal-v2 真实候选）：「价格从780到1180元」一端命中砚泊 30 mL 价格即不告警。"""
    request = rec104_request()
    facts = load_facts(request, root=isolated_root)
    real_texts = [
        "林女士，朋友没提过偏好，确实不好替她定。1200元以内，这次可以看青岚 50 mL 980元、暮光 50 mL 1080元、雨白 50 mL 1180元，砚泊 30 mL 780元。四款风格差得比较开，稳妥一点的话，可以先想想她平时是偏清爽、偏花香，还是偏木质。",
        "林女士，您自己喜欢柔和的玫瑰气息，但送礼还是得按朋友的喜好来，这点我不替您猜。预算内可选的有青岚、暮光、雨白各50 mL，还有砚泊 30 mL，价格从780到1180元。您要是能说一两句她平时的穿衣或气味偏好，我帮您把范围缩小。",
        "林女士，朋友偏好还不清楚的话，不建议直接定一瓶。四款都可以到店试闻，您先来闻一圈，再挑您觉得更贴近她气质的那支；也可以约朋友一起来。您方便的话告诉我大概什么时候来，我请门店同事和您确认试闻安排。",
    ]
    candidates = [Candidate(candidate_id=f"REC-104-C{i}", text=text) for i, text in enumerate(real_texts, 1)]
    assert check_explicit_facts(candidates, facts, request) == []


def test_range_with_both_endpoints_unmatched_still_warned(isolated_root: Path):
    """对照组：区间两端点都匹配不上该容量 SKU 价格时仍要告警。"""
    request = GenerationRequest(scenario="产品推荐",
        client_information={"current_need": "送朋友"}, product_ids=["YANBO-30"])
    facts = load_facts(request, root=isolated_root)
    candidate = Candidate(candidate_id="T", text="砚泊 30 mL，价格从900到1180元。")
    warnings = check_explicit_facts([candidate], facts, request)
    assert any("请核对是品牌报价还是顾客原话" in warning for warning in warnings)


def test_unknown_volume_still_warned(isolated_root: Path):
    """规格不存在告警保持：75 毫升不在本次商品资料中。"""
    request = GenerationRequest(scenario="价格异议",
        client_information={"current_need": "想买青岚"}, product_ids=["QINGLAN-50"])
    facts = load_facts(request, root=isolated_root)
    candidate = Candidate(candidate_id="T", text="青岚75毫升是1200元。")
    warnings = check_explicit_facts([candidate], facts, request)
    assert any("75 mL 未在本次商品资料中找到" in warning for warning in warnings)


def test_single_point_mismatch_still_warned(isolated_root: Path):
    """单点金额不匹配告警保持：青岚 50 mL 写成 1580 元仍要告警。"""
    request = GenerationRequest(scenario="价格异议",
        client_information={"current_need": "想买青岚"}, product_ids=["QINGLAN-50"])
    facts = load_facts(request, root=isolated_root)
    candidate = Candidate(candidate_id="T", text="青岚50毫升是1580元。")
    warnings = check_explicit_facts([candidate], facts, request)
    assert any("请核对是品牌报价还是顾客原话" in warning for warning in warnings)


def test_history_year_not_whitelisted(isolated_root: Path):
    """裸数字收白名单时排除年份：紧跟「年」的 2026 不抑制金额告警。"""
    request = GenerationRequest(scenario="价格异议",
        client_information={"current_need": "暮光贵"},
        conversation_history=[{"role": "client", "content": "2026年我买过暮光。"}],
        product_ids=["MUGUANG-50"])
    facts = load_facts(request, root=isolated_root)
    candidate = Candidate(candidate_id="T", text="暮光50毫升是2026元。")
    warnings = check_explicit_facts([candidate], facts, request)
    assert any("请核对是品牌报价还是顾客原话" in warning for warning in warnings)


def test_history_volume_numbers_not_whitelisted(isolated_root: Path):
    """裸数字收白名单时排除容量单位：紧跟「毫升」的 100 不抑制金额告警。"""
    request = GenerationRequest(scenario="价格异议",
        client_information={"current_need": "想买青岚"},
        conversation_history=[{"role": "client", "content": "100毫升看着单价低。"}],
        product_ids=["QINGLAN-50"])
    facts = load_facts(request, root=isolated_root)
    candidate = Candidate(candidate_id="T", text="青岚50毫升是100元。")
    warnings = check_explicit_facts([candidate], facts, request)
    assert any("请核对是品牌报价还是顾客原话" in warning for warning in warnings)


def test_history_date_adjacent_number_not_whitelisted(isolated_root: Path):
    """裸数字收白名单时排除日期紧邻语境：紧跟「日」的 980 不抑制金额告警。"""
    request = GenerationRequest(scenario="价格异议",
        client_information={"current_need": "暮光贵"},
        conversation_history=[{"role": "client", "content": "8月8日980，当天说的。"}],
        product_ids=["MUGUANG-50"])
    facts = load_facts(request, root=isolated_root)
    candidate = Candidate(candidate_id="T", text="暮光50毫升是980元。")
    warnings = check_explicit_facts([candidate], facts, request)
    assert any("请核对是品牌报价还是顾客原话" in warning for warning in warnings)
