"""确定性中文去 AI 味检查器：纯函数、无模型调用、不新增事实。

lint_text 只报告（顾问可见），clean_text 只做高置信、不改变语义的确定性清理：
删除万能结尾句、客服开场短语与插入语短语；其余命中只报告不清洗。
"""

from __future__ import annotations

import re

# 万能结尾句：整句可删（连同前导逗号/分号）。
_CLOSING_PHRASES = r"祝您生活愉快|期待您的回复|如还有其他需要请随时联系我|希望能帮到您|如有任何问题请随时联系|我将尽快为您处理"
# 客服开场短语。
_OPENER_PHRASES = r"很高兴为您服务|非常高兴为您服务|感谢您的咨询"
# 插入语短语。
_FILLER_PHRASES = r"值得注意的是|需要说明的是|值得一提的是"

AI_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("万能结尾", re.compile(_CLOSING_PHRASES), "万能结尾句，建议删除或改为具体下一步。"),
    ("客服开场", re.compile(_OPENER_PHRASES), "客服式开场白，建议直接进入正题。"),
    ("总起句", re.compile(r"关于您提到的|针对您的问题|关于这个问题"), "总起句，建议直接回答具体问题。"),
    ("插入语", re.compile(_FILLER_PHRASES), "插入语，建议删除。"),
    ("负面平行", re.compile(r"不是.{0,20}?而是|不仅.{0,20}?还|与其说.{0,20}?不如说"), "负面平行/递进结构，AI 味明显，建议改写。"),
    ("意义后缀", re.compile(r"体现了|展现了|象征着|承载着|诠释了"), "意义升华后缀，建议用具体事实替代。"),
    ("抒情堆砌", re.compile(r"在这特别的日子里|愿您的每一天都|被幸福环绕|美好的每一天"), "抒情堆砌，建议删除或改为具体祝福。"),
    ("AI词表", re.compile(r"打造|赋能|抓手|闭环|沉淀|匠心|极致|沉浸式|触达|生态|维度|颗粒度|落地|彰显|承载|诠释|高级感|氛围感|治愈|邂逅|仪式感|格调|旅程|绽放|点亮|开启.{0,8}?之旅"), "AI 高频词，建议替换为具体表达。"),
    ("祝福叠愿", re.compile(r"愿"), "同一句中「愿」出现 3 次及以上，祝福堆叠。"),
    ("语气词密度", re.compile(r"[～啦哈哦呢]"), "语气词密度过高（「～」×2 或句尾语气词×3 及以上）。"),
    ("元叙述", re.compile(r"就这一句|简单一句|只说一句|不多打扰|不打扰您|不打扰了|不用急着回|不用回复|我记下了|记着这句话|记着您说|按您的意思|只想把这句送到|先说一句|先不多说|冒昧打扰|打扰一句"), "元叙述（交代写作过程的话），客户不需要知道，建议删除。"),
)

_SENTENCE_RE = re.compile(r"[^。！？!?；;]*[。！？!?；;]?")
_CLAUSE_SPLIT_RE = re.compile(r"[，,。！？!?；;]+")
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]{10,}")
_CLIENT_ROLES = {"client", "customer", "user"}
_NORMALIZE_RE = re.compile(r"[\s，,。！？!?；;：:、·…—–\-～~“”‘’「」『』（）()《》<>【】\[\]…]")
_BIRTHDAY_PROMO_RE = re.compile(r"青岚|暮光|雨白|砚泊|试闻|到店|购买|上新|优惠|活动|折扣|推荐|比较|登记|留个位置|名额")

# 清洗规则：仅这三类高置信清理；短语后须跟句读或文本结尾，避免切断仍在继续的句子。
_CLOSE_CLEAN_RE = re.compile(r"[，,；;]?(?:" + _CLOSING_PHRASES + r")(?=[，,；;。！？!?]|$)[，,；;。！？!?]?")
_OPENER_CLEAN_RE = re.compile(r"(?:" + _OPENER_PHRASES + r")(?=[，,；;。！？!?]|$)[，,。！？!?；;]?")
_FILLER_CLEAN_RE = re.compile(r"[，,]?(?:" + _FILLER_PHRASES + r")(?=[，,；;。！？!?]|$)[，,]?")


def _sentences(text: str) -> list[re.Match[str]]:
    return [match for match in _SENTENCE_RE.finditer(text) if match.group().strip()]


def _clauses(text: str) -> list[str]:
    return [part.strip() for part in _CLAUSE_SPLIT_RE.split(text) if part.strip()]


def _normalize(text: str) -> tuple[str, list[int]]:
    """去除空白与常见标点；返回归一化文本及每个归一化字符在原文中的位置。"""
    chars: list[str] = []
    index_map: list[int] = []
    for index, char in enumerate(text):
        if _NORMALIZE_RE.fullmatch(char):
            continue
        chars.append(char)
        index_map.append(index)
    return "".join(chars), index_map


def _longest_common_substring(first: str, second: str) -> str:
    """返回 first 中出现在 second 里的最长子串（要求 ≥10 个字符）；没有则返回空串。"""
    limit = min(len(first), len(second))
    for length in range(limit, 9, -1):
        for start in range(0, len(first) - length + 1):
            if first[start:start + length] in second:
                return first[start:start + length]
    return ""


def _context_duplication_hits(text: str, conversation_history: list[dict]) -> list[tuple[int, dict]]:
    """候选与客户原话（role in {client, customer, user}）重复 ≥10 个连续 CJK 字符的片段，仅报告。"""
    if not conversation_history:
        return []
    sources = []
    for turn in conversation_history:
        role = turn.get("role")
        content = turn.get("content")
        if role in _CLIENT_ROLES and isinstance(content, str) and content.strip():
            sources.append((role, _normalize(content)[0]))
    if not sources:
        return []
    candidate_norm, index_map = _normalize(text)
    hits: list[tuple[int, dict]] = []
    for run_match in _CJK_RUN_RE.finditer(candidate_norm):
        run = run_match.group()
        best: tuple[int, str, str] | None = None
        for role, source in sources:
            fragment = _longest_common_substring(run, source)
            if fragment and (best is None or len(fragment) > best[0]):
                best = (len(fragment), fragment, role)
        if best:
            _length, fragment, role = best
            display = fragment if len(fragment) <= 40 else fragment[:40] + "…"
            hits.append((index_map[run_match.start()], {"category": "上下文重复", "match": display, "message": f"该片段与客户原话重复（来源：{role} 消息），建议用顾问自己的话改写。"}))
    return hits


def _scenario_hits(text: str, scenario: str | None) -> list[tuple[int, dict]]:
    """生日与节庆场景：候选中出现商品名或推销词时仅报告，不修改文本。"""
    if scenario != "生日与节庆":
        return []
    hits: list[tuple[int, dict]] = []
    for match in _BIRTHDAY_PROMO_RE.finditer(text):
        hits.append((match.start(), {"category": "场景不适配", "match": match.group(), "message": "生日祝福不应包含商品或推销内容，请删除或改写。"}))
    return hits


def lint_text(text: str, *, conversation_history: list[dict] | None = None, scenario: str | None = None) -> list[dict]:
    """返回命中项 [{category, match, message}]，按出现位置排序；只报告，不修改文本。

    conversation_history 用于上下文重复检测（客户角色消息为来源）；scenario 用于场景适配检测。
    """
    hits: list[tuple[int, dict]] = []
    for category, pattern, message in AI_PATTERNS:
        if category == "祝福叠愿":
            for sentence in _sentences(text):
                content = sentence.group()
                count = content.count("愿")
                if count >= 3:
                    hits.append((sentence.start(), {"category": category, "match": content.strip(), "message": f"同一句中「愿」出现 {count} 次，祝福堆叠。"}))
        elif category == "语气词密度":
            tilde_count = text.count("～")
            if tilde_count >= 2:
                hits.append((0, {"category": category, "match": text, "message": f"「～」出现 {tilde_count} 次（≥2），语气词密度过高。"}))
            tails = [clause for clause in _clauses(text) if clause[-1] in "啦哈哦呢"]
            if len(tails) >= 3:
                hits.append((text.find(tails[0]), {"category": category, "match": "｜".join(tails), "message": f"句尾语气词（啦/哈/哦/呢）出现 {len(tails)} 处（≥3），语气词密度过高。"}))
        else:
            for match in pattern.finditer(text):
                hits.append((match.start(), {"category": category, "match": match.group(), "message": message}))
    hits.extend(_context_duplication_hits(text, conversation_history or []))
    hits.extend(_scenario_hits(text, scenario))
    hits.sort(key=lambda item: item[0])
    return [hit for _, hit in hits]


def clean_text(text: str) -> tuple[str, list[str]]:
    """确定性清理：删除万能结尾句、客服开场短语、插入语短语；其余命中不处理。返回 (清洗后文本, 已应用规则类别)。"""
    applied: list[str] = []
    cleaned = text
    before = cleaned
    cleaned = _CLOSE_CLEAN_RE.sub("", cleaned)
    if cleaned != before:
        applied.append("万能结尾")
    before = cleaned
    cleaned = _OPENER_CLEAN_RE.sub("", cleaned)
    if cleaned != before:
        applied.append("客服开场")
    before = cleaned
    cleaned = _FILLER_CLEAN_RE.sub("", cleaned)
    if cleaned != before:
        applied.append("插入语")
    cleaned = re.sub(r"[，,]{2,}", "，", cleaned)
    cleaned = re.sub(r"[；;]{2,}", "；", cleaned)
    return cleaned.strip(), applied
