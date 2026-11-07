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
)

_SENTENCE_RE = re.compile(r"[^。！？!?；;]*[。！？!?；;]?")
_CLAUSE_SPLIT_RE = re.compile(r"[，,。！？!?；;]+")

# 清洗规则：仅这三类高置信清理；短语后须跟句读或文本结尾，避免切断仍在继续的句子。
_CLOSE_CLEAN_RE = re.compile(r"[，,；;]?(?:" + _CLOSING_PHRASES + r")(?=[，,；;。！？!?]|$)[，,；;。！？!?]?")
_OPENER_CLEAN_RE = re.compile(r"(?:" + _OPENER_PHRASES + r")(?=[，,；;。！？!?]|$)[，,。！？!?；;]?")
_FILLER_CLEAN_RE = re.compile(r"[，,]?(?:" + _FILLER_PHRASES + r")(?=[，,；;。！？!?]|$)[，,]?")


def _sentences(text: str) -> list[re.Match[str]]:
    return [match for match in _SENTENCE_RE.finditer(text) if match.group().strip()]


def _clauses(text: str) -> list[str]:
    return [part.strip() for part in _CLAUSE_SPLIT_RE.split(text) if part.strip()]


def lint_text(text: str) -> list[dict]:
    """返回命中项 [{category, match, message}]，按出现位置排序；只报告，不修改文本。"""
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
