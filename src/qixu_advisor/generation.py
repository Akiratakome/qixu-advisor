"""Streamlit 与批量 CLI 共用的一次生成流程。"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .data import PROJECT_ROOT, contact_is_blocked, load_facts, required_information
from .de_ai import clean_text, lint_text
from .model import ModelCallError, ModelConfig, call_model, get_config, public_config
from .models import AnalysisResult, Candidate, GenerationRequest, GenerationResult, valid_id
from .records import append_jsonl, begin_case, save_result, source_versions, timestamp


class _Draft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=3000)


class _Drafts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidates: list[_Draft] = Field(min_length=3, max_length=3)


DEFAULT_GOALS = {
    "生日与节庆": "answer",
    "产品推荐": "recommend",
    "购后关怀": "answer",
    "沉睡唤醒": "next_step",
    "活动邀请": "next_step",
    "价格异议": "answer",
}

LANGUAGE_LABELS = {"zh-CN": "中文（zh-CN）", "en": "英文（en）"}
TONE_LABELS = {"natural": "自然", "warm": "温和", "direct": "直接"}
LENGTH_LABELS = {"short": "简短", "standard": "标准"}
GOAL_LABELS = {"answer": "回答问题", "recommend": "帮助选择", "next_step": "提出下一步"}

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_ASCII_LETTER_RE = re.compile(r"[A-Za-z]")
_AMOUNT_RE = re.compile(r"(?:¥|￥)\s*(\d[\d,]*(?:\.\d+)?)|(\d[\d,]*(?:\.\d+)?)\s*(?:元|块)")
_BUDGET_CONTEXT_RE = re.compile(r"(?:预算|最多|不超过|以内|上限)[^0-9¥￥\n]{0,8}?(\d[\d,]*(?:\.\d+)?)")
# 聊天中的三位及以上裸数字也算客户原话金额；紧邻日期语境（年月日天号时分秒点周）或容量单位的数字不收。
_BARE_AMOUNT_RE = re.compile(r"(?<![年月日天号时分秒点周\d])\d[\d,]{2,}(?:\.\d+)?(?![\d年月日天号时分秒点周])(?!\s*(?:毫升|mL|ml|ML))")
_CLAUSE_BREAK_RE = re.compile(r"[。；;\n]")
_VOLUME_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:mL|ml|ML|毫升)")
_SINGLE_PRICE_RE = re.compile(r"(?:¥|￥)\s*(\d[\d,]*(?:\.\d+)?)|(\d[\d,]*(?:\.\d+)?)\s*(?:元|块)")
_RANGE_PRICE_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(?:到|至|-|–|—|－)\s*(\d[\d,]*(?:\.\d+)?)\s*(?:元|块)")
# 显式合计语境：候选自己推算总价的标记；金额还必须恰为目录价的小整数倍才豁免告警。
_TOTAL_CONTEXT_RE = re.compile(r"(?:合计|共计|总共|一共|总计|加起来|[0-9两三四五六七八九十]\s*瓶)")
# 「A 和 B 分别是 X 元和 Y 元」：容量与金额按顺序一一对应，不再按就近配对。
_LIST_CONNECTOR_RE = re.compile(r"分别是|分别为|依次是|各为|依次为")
_LIST_JOINER_RE = re.compile(r"[\s和与、]*")


def effective_settings(request: GenerationRequest) -> dict[str, Any]:
    """goal=None 时按场景解析默认目标；显式设置优先，供提示组装与 provenance 共用。"""
    goal = request.goal if request.goal is not None else DEFAULT_GOALS[request.scenario]
    return {
        "output_language": request.output_language,
        "tone": request.tone,
        "length": request.length,
        "goal": goal,
        "goal_source": "explicit" if request.goal is not None else "scenario_default",
    }


def text_matches_language(text: str, output_language: str) -> bool:
    """zh-CN 须含 CJK 字符；en 须含 ASCII 字母。"""
    if output_language == "zh-CN":
        return bool(_CJK_RE.search(text))
    if output_language == "en":
        return bool(_ASCII_LETTER_RE.search(text))
    return False


def load_approved_examples(*, root: Path = PROJECT_ROOT) -> list[dict[str, Any]]:
    """经审阅参考示例：文件缺失或为空时返回 []；结构非法行显式报错，不静默跳过。"""
    path = Path(root) / "data" / "style_examples" / "approved.jsonl"
    if not path.exists():
        return []
    records = []
    for index, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"经审阅参考示例第 {index} 行不是合法 JSON：{exc}") from exc
        if not isinstance(record, dict) or not str(record.get("text", "")).strip():
            raise ValueError(f"经审阅参考示例第 {index} 行结构非法：须为含非空 text 字段的 JSON 对象")
        records.append(record)
    return records


def build_messages(request: GenerationRequest, facts: dict[str, Any], *, root: Path = PROJECT_ROOT) -> list[dict[str, str]]:
    prompt_dir = Path(root) / "src" / "qixu_advisor" / "prompts"
    system = (prompt_dir / "system.txt").read_text(encoding="utf-8")
    rules_path = prompt_dir / "writing_rules.md"
    if rules_path.exists():
        system += "\n\n【写作规则】\n" + rules_path.read_text(encoding="utf-8").strip()
    settings = effective_settings(request)
    goal_text = GOAL_LABELS[settings["goal"]]
    if settings["goal_source"] == "scenario_default":
        goal_text += "（场景默认）"
    settings_lines = [f"- 输出语言：{LANGUAGE_LABELS[settings['output_language']]}"]
    if settings["output_language"] == "en":
        settings_lines.append("【最高优先】本组三条候选必须全部使用英文撰写，输出中文即视为不合格；商品规范名保留中文原文（青岚、暮光、雨白、砚泊）；币种人民币、规格、日期与时区不变。")
    settings_lines += [
        f"- 语气：{TONE_LABELS[settings['tone']]}",
        f"- 篇幅：{LENGTH_LABELS[settings['length']]}",
        f"- 本次目标：{goal_text}",
    ]
    system += "\n\n【写作设置】\n" + "\n".join(settings_lines) + "\n"
    if settings["output_language"] == "en":
        system = "【语言要求】本次任务所有输出必须使用英文（仅英文，不得输出中文）；商品规范名保留中文原文（青岚、暮光、雨白、砚泊）；币种人民币、规格、日期与时区不变。\n\n" + system
    scenes = json.loads((prompt_dir / "scenarios.json").read_text(encoding="utf-8"))
    system += "\n本场景要求：" + scenes[request.scenario]
    examples = load_approved_examples(root=root)
    if examples:
        rendered = []
        for record in examples:
            label = f"（{record['scenario']}）" if record.get("scenario") else ""
            rendered.append(f"- {label}{record['text'].strip()}")
        system += "\n\n【经审阅参考示例】\n" + "\n".join(rendered)
    if settings["output_language"] == "en":
        system += "\n\nLanguage reminder: write all three candidates entirely in English; keep product names in Chinese."
    user_content = json.dumps({"request": request.model_dump(mode="json"), "facts": facts}, ensure_ascii=False)
    if settings["output_language"] == "en":
        user_content = "【语言】请仅用英文撰写三条候选，商品名保留中文。\n" + user_content
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]


def _edit_distance(first: str, second: str) -> int:
    if len(first) < len(second):
        first, second = second, first
    previous = list(range(len(second) + 1))
    for row, char_a in enumerate(first, 1):
        current = [row]
        for column, char_b in enumerate(second, 1):
            current.append(min(previous[column] + 1, current[column - 1] + 1, previous[column - 1] + (char_a != char_b)))
        previous = current
    return previous[-1]


def _close(value: float, pool: set[float]) -> bool:
    return any(abs(value - item) < 1e-6 for item in pool)


def _is_derived_total(value: float, fact_prices: set[float], prefix: str) -> bool:
    """金额处在显式合计语境（合计/两瓶等）且恰为目录价 2–9 倍，视为候选自己的正确推算，不告警。"""
    if not _TOTAL_CONTEXT_RE.search(prefix):
        return False
    for price in fact_prices:
        multiple = round(value / price)
        if abs(value / price - multiple) < 1e-6 and 2 <= multiple <= 9:
            return True
    return False


_TOTAL_CLAUSE_BREAKS = "。；;！!？?\n"


def _total_context_prefix(text: str, end: int) -> str:
    """合计语境前缀：从金额向前取至最近一个句读（。；;！?\\n）或最多 40 字符，两者取短。"""
    window = text[max(0, end - 40):end]
    cut = -1
    for char in _TOTAL_CLAUSE_BREAKS:
        cut = max(cut, window.rfind(char))
    return window[cut + 1:]


def _is_derived_amount(value: float, products: list[dict[str, Any]], whitelist: set[float]) -> bool:
    """推导金额：单位价（资料价格/容量，容差 0.05 元/毫升）或两个价格之差的绝对值（含白名单金额与事实价之差）。
    单价符号即使不出现在资料中也按推导处理；推导金额不告警。"""
    fact_prices: set[float] = set()
    for item in products:
        price = item.get("price_cny")
        volume = item.get("volume_ml")
        if not (isinstance(price, (int, float)) and not isinstance(price, bool) and isinstance(volume, (int, float)) and not isinstance(volume, bool) and volume):
            continue
        fact_prices.add(float(price))
        if abs(value - float(price) / float(volume)) < 0.05:
            return True
    for first in fact_prices:
        for second in fact_prices | whitelist:
            if abs(value - abs(first - second)) < 1e-6:
                return True
    return False


def _budget_whitelist(request: GenerationRequest | None) -> set[float]:
    """白名单金额=客户原话（预算字段与聊天中出现的金额），不是本品牌报价。"""
    amounts: set[float] = set()
    if request is None:
        return amounts

    def add(value: str) -> None:
        cleaned = value.replace(",", "").strip()
        if cleaned:
            amounts.add(float(cleaned))

    budget = request.client_information.get("budget_cny")
    if isinstance(budget, bool):
        budget = None
    if isinstance(budget, (int, float)):
        add(str(budget))
    elif isinstance(budget, str) and re.fullmatch(r"\d[\d,]*(?:\.\d+)?", budget.strip()):
        add(budget)
    history_text = "\n".join(turn.get("content", "") for turn in request.conversation_history)
    for match in _AMOUNT_RE.finditer(history_text):
        add(match.group(1) or match.group(2))
    for match in _BUDGET_CONTEXT_RE.finditer(history_text):
        add(match.group(1))
    # 无币种标记的客户原话金额（如「昨天说980，今天怎么变1080」）；年份与容量数字不进白名单。
    for match in _BARE_AMOUNT_RE.finditer(history_text):
        add(match.group(0))
    return amounts


def check_explicit_facts(candidates: list[Candidate], facts: dict[str, Any], request: GenerationRequest | None = None) -> list[str]:
    """只提示能定位的商品容量/金额矛盾、疑似商品名错字与未归属金额；告警仅顾问可见，绝不改变候选。"""
    products = facts.get("products", [])
    names = sorted({item.get("name", "") for item in products if item.get("name")}, key=len, reverse=True)
    if not names:
        return []
    whitelist = _budget_whitelist(request)
    fact_prices = {float(item["price_cny"]) for item in products if isinstance(item.get("price_cny"), (int, float)) and not isinstance(item.get("price_cny"), bool)}
    materials_text = json.dumps({"facts": facts, "client_information": request.client_information if request else {}, "conversation_history": request.conversation_history if request else []}, ensure_ascii=False)
    names_pattern = "|".join(re.escape(name) for name in names)
    warnings = []
    for candidate in candidates:
        mentions = list(re.finditer(names_pattern, candidate.text))
        for index, mention in enumerate(mentions):
            end = mentions[index + 1].start() if index + 1 < len(mentions) else len(candidate.text)
            fragment = candidate.text[mention.end():end]
            name = mention.group()
            variants = [item for item in products if item.get("name") == name]
            # 每个容量只与「容量→金额」邻近窗口内的第一个金额配对：窗口到下一个容量、句读或 30 字符为止，
            # 片段里稍远处属于另一个容量的价格不得跨配。
            volume_tokens = [(match.start(), match.end(), float(match.group(1))) for match in _VOLUME_RE.finditer(fragment)]
            amount_tokens: list[tuple[int, int, str, Any]] = []
            range_spans: list[tuple[int, int]] = []
            for match in _RANGE_PRICE_RE.finditer(fragment):
                range_spans.append((match.start(), match.end()))
                amount_tokens.append((match.start(), match.end(), "range", (float(match.group(1).replace(",", "")), float(match.group(2).replace(",", "")))))
            for match in _SINGLE_PRICE_RE.finditer(fragment):
                if any(match.start() < range_end and match.end() > range_start for range_start, range_end in range_spans):
                    continue
                amount_tokens.append((match.start(), match.end(), "price", float((match.group(1) or match.group(2)).replace(",", ""))))
            amount_tokens.sort(key=lambda token: token[0])

            def check_pair(volume: float, kind: str, value: Any, amount_start: int) -> None:
                matching = [item for item in variants if float(item.get("volume_ml", -1)) == volume]
                if not matching:
                    warnings.append(f"{candidate.candidate_id}：{name} {volume:g} mL 未在本次商品资料中找到，请核对规格。")
                    return
                prefix = _total_context_prefix(fragment, amount_start)
                if kind == "range":
                    low, high = value
                    if low > high:
                        low, high = high, low
                    prices = {float(item.get("price_cny", -1)) for item in matching}
                    if not (_close(low, prices) or _close(high, prices)):
                        expected = " / ".join(f"{item['price_cny']} 元" for item in matching)
                        warnings.append(f"{candidate.candidate_id}：{name} {volume:g} mL 附近出现 {low:g} 到 {high:g} 元，资料价格为 {expected}；请核对是品牌报价还是顾客原话。")
                    return
                price = value
                if not _close(price, whitelist) and not _is_derived_total(price, fact_prices, prefix) and not _is_derived_amount(price, products, whitelist) and not any(_close(price, {float(item.get("price_cny", -1))}) for item in matching):
                    expected = " / ".join(f"{item['price_cny']} 元" for item in matching)
                    warnings.append(f"{candidate.candidate_id}：{name} {volume:g} mL 附近出现 {price:g} 元，资料价格为 {expected}；请核对是品牌报价还是顾客原话。")

            consumed_volumes: set[int] = set()
            consumed_amounts: set[int] = set()
            # 「50 mL 和 100 mL 标价分别是 980 元和 1580 元」：容量与金额按顺序一一对应。
            connector = _LIST_CONNECTOR_RE.search(fragment)
            if connector:
                volumes_before = [token for token in volume_tokens if token[0] < connector.start()]
                amounts_after = [token for token in amount_tokens if token[0] >= connector.end() and token[0] - connector.end() <= 12]
                chain = amounts_after[:1]
                for previous, following in zip(amounts_after, amounts_after[1:]):
                    if _LIST_JOINER_RE.fullmatch(fragment[previous[1]:following[0]]):
                        chain.append(following)
                    else:
                        break
                if volumes_before and len(volumes_before) == len(chain):
                    for (volume_start, volume_end, volume), (amount_start, amount_end, kind, value) in zip(volumes_before, chain):
                        check_pair(volume, kind, value, amount_start)
                        consumed_volumes.add(volume_start)
                        consumed_amounts.add(amount_start)
            # 其余容量只与「容量→金额」邻近窗口内的第一个金额配对：窗口到下一个容量、句读或 30 字符为止，
            # 片段里稍远处属于另一个容量的价格不得跨配。
            for volume_index, (volume_start, volume_end, volume) in enumerate(volume_tokens):
                if volume_start in consumed_volumes:
                    continue
                next_volume_start = volume_tokens[volume_index + 1][0] if volume_index + 1 < len(volume_tokens) else None
                for start, _end, kind, value in amount_tokens:
                    if start in consumed_amounts or start <= volume_end:
                        continue
                    if next_volume_start is not None and start > next_volume_start:
                        break
                    between = fragment[volume_end:start]
                    if len(between) > 30 or _CLAUSE_BREAK_RE.search(between):
                        break
                    check_pair(volume, kind, value, start)
                    break
        for name in names:
            width = len(name)
            if width < 2:
                continue
            for start in range(len(candidate.text) - width + 1):
                window = candidate.text[start:start + width]
                if not all("\u4e00" <= char <= "\u9fff" for char in window):
                    continue
                if window == name or window in materials_text:
                    continue
                if _edit_distance(window, name) == 1:
                    warnings.append(f"{candidate.candidate_id}：疑似商品名错字：{window}（资料规范名：{name}）")
                    break
        for match in _AMOUNT_RE.finditer(candidate.text):
            value = float((match.group(1) or match.group(2)).replace(",", ""))
            if _close(value, fact_prices) or _close(value, whitelist):
                continue
            if _is_derived_total(value, fact_prices, _total_context_prefix(candidate.text, match.start())):
                continue
            if _is_derived_amount(value, products, whitelist):
                continue
            warnings.append(f"{candidate.candidate_id}：候选出现 {value:g} 元；该金额未在本次资料中出现，请核对来源。")
    return list(dict.fromkeys(warnings))


def _apply_de_ai_gate(candidates: list[Candidate], output_language: str, conversation_history: list[dict[str, Any]] | None = None, scenario: str | None = None) -> tuple[list[Candidate], dict[str, Any]]:
    """输出前必须过一遍的去 AI 味门槛：逐条 lint（含上下文重复与场景适配，仅报告）并做确定性清洗；清洗是规则、不是模型重写、不新增事实。"""
    originals = [candidate.text for candidate in candidates]
    cleaned_versions: list[str] = []
    applied_rules: list[list[str]] = []
    per_candidate = []
    for candidate in candidates:
        hits = lint_text(candidate.text, conversation_history=conversation_history, scenario=scenario)
        cleaned, applied = clean_text(candidate.text)
        cleaned_versions.append(cleaned)
        applied_rules.append(applied)
        per_candidate.append({"candidate_id": candidate.candidate_id, "lint_hits": hits, "cleaned": False, "applied_rules": []})
    final_texts: list[str] = []
    for index, candidate in enumerate(candidates):
        original_text = originals[index]
        cleaned = cleaned_versions[index]
        entry = per_candidate[index]
        if cleaned == original_text:
            final_texts.append(original_text)
            continue
        if not cleaned:
            entry["skipped_reason"] = "清洗后为空"
            final_texts.append(original_text)
            continue
        if not text_matches_language(cleaned, output_language):
            entry["skipped_reason"] = "清洗后不符合输出语言设置"
            final_texts.append(original_text)
            continue
        other_originals = {originals[other] for other in range(len(candidates)) if other != index}
        other_cleaned = {cleaned_versions[other] for other in range(len(candidates)) if other != index and cleaned_versions[other]}
        if cleaned in other_originals or cleaned in other_cleaned:
            entry["skipped_reason"] = "清洗后与其他候选重复"
            final_texts.append(original_text)
            continue
        entry["cleaned"] = True
        entry["applied_rules"] = applied_rules[index]
        final_texts.append(cleaned)
    cleaned_candidates = [Candidate(candidate_id=candidate.candidate_id, text=text) for candidate, text in zip(candidates, final_texts)]
    return cleaned_candidates, {"gate": "applied", "per_candidate": per_candidate}


def generate(request: GenerationRequest | dict[str, Any], run_id: str, case_id: str, *, root: Path = PROJECT_ROOT, model_call: Callable[[list[dict[str, str]], ModelConfig], dict[str, Any]] | None = None, execution_mode: str = "real", config: ModelConfig | None = None) -> GenerationResult:
    """一次请求只调用一次模型，先保存输入和原始返回，再检验结构。

    config 显式传入（如界面自配的运行时设置）时直接使用，跳过内部 get_config；默认 None 保持现有行为。
    """
    valid_id(run_id)
    valid_id(case_id)
    request = GenerationRequest.model_validate(request)
    if model_call is not None and execution_mode != "stub":
        raise ValueError("注入测试替身必须显式标记 execution_mode='stub'")
    if execution_mode == "stub" and model_call is None:
        raise ValueError("stub 模式须提供替身，不能调用真实模型")
    start = time.perf_counter()
    facts: dict[str, Any] = {}
    messages: list[dict[str, str]] = []
    setup_error = None
    try:
        facts = load_facts(request, root=root)
        messages = build_messages(request, facts, root=root)
        config = config if config is not None else get_config(root)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        setup_error = f"本地资料、提示或配置读取失败（{type(exc).__name__}），请检查文件与参数"
        config = ModelConfig()
    provenance = {"execution_mode": execution_mode, "created_at": timestamp(), "versions": source_versions(root), "model_config": public_config(config), "model_call_count": 0, "quality_status": "not_human_evaluated", "effective_settings": effective_settings(request)}
    path = begin_case(run_id, case_id, {"schema_version": "1.0", "run_id": run_id, "case_id": case_id, "created_at": timestamp(), "request": request.model_dump(mode="json"), "facts": facts, "messages": messages, "provenance": provenance}, root=root, execution_mode=execution_mode)

    def finish(status: str, **fields: Any) -> GenerationResult:
        result = GenerationResult(run_id=run_id, case_id=case_id, status=status, fact_references=facts.get("references", []), provenance={**provenance, "elapsed_seconds": time.perf_counter() - start}, **fields)
        # 保存失败直接抛出，调用端不得把未保存的结果展示成完整成功。
        save_result(result, root=root)
        return result

    if setup_error:
        return finish("technical_failure", error=setup_error)
    if contact_is_blocked(request, facts):
        return finish("contact_blocked", error="资料明确禁止联系，本次未调用模型")
    missing = required_information(request, facts)
    if missing:
        return finish("needs_input", missing_fields=missing)
    if execution_mode == "real" and not config.api_key.get_secret_value().strip():
        return finish("technical_failure", error="未配置 DEEPSEEK_API_KEY；未发起真实模型请求")

    attempt = {"attempt": 1, "started_at": timestamp(), "execution_mode": execution_mode, "model_config": public_config(config)}
    caller = model_call or call_model
    try:
        response = caller(messages, config)
        provenance["model_call_count"] = 1
        attempt.update(response)
        attempt["status"] = "received"
    except ModelCallError as exc:
        provenance["model_call_count"] = int(exc.details.get("attempted", True))
        attempt.update({"status": "error", "error": str(exc), **exc.details})
        append_jsonl(path / "attempts.jsonl", attempt)
        return finish("technical_failure", error=str(exc))
    except Exception as exc:
        # 非预期适配器错误不记录异常文本，防止其中包含环境凭据。
        provenance["model_call_count"] = 1
        error = f"模型调用发生 {type(exc).__name__}；未自动重试"
        attempt.update({"status": "error", "error": error})
        append_jsonl(path / "attempts.jsonl", attempt)
        return finish("technical_failure", error=error)
    # 原始响应在解析之前落盘；结构不合格也能回溯首轮返回。
    append_jsonl(path / "attempts.jsonl", attempt)
    provenance.update({"returned_model": response.get("model"), "usage": response.get("usage", {}), "model_elapsed_seconds": response.get("elapsed_seconds")})
    try:
        if response.get("finish_reason") not in {None, "stop"}:
            raise ValueError("输出未正常结束")
        drafts = _Drafts.model_validate_json(response["raw_text"])
        candidates = [Candidate(candidate_id=f"{case_id}-C{index}", text=draft.text) for index, draft in enumerate(drafts.candidates, 1)]
        if len({candidate.text for candidate in candidates}) != 3:
            raise ValueError("三条候选完全重复")
        if not all(text_matches_language(candidate.text, request.output_language) for candidate in candidates):
            raise ValueError(f"候选语言不符合输出语言设置（{request.output_language}）")
    except (ValidationError, ValueError, KeyError, TypeError):
        return finish("technical_failure", error=f"模型输出结构不合格：需要三条不同、非空且符合输出语言设置（{request.output_language}）的完整候选；原始返回已保存，未重抽")
    candidates, de_ai_report = _apply_de_ai_gate(candidates, request.output_language, request.conversation_history, request.scenario)
    provenance["de_ai_gate"] = "applied"
    return finish("success", candidates=candidates, warnings=check_explicit_facts(candidates, facts, request), de_ai_report=de_ai_report)


def analyze_conversation(conversation_history: list[dict[str, Any]], client_information: dict[str, Any] | None, *, root: Path = PROJECT_ROOT, model_call: Callable[[list[dict[str, str]], ModelConfig], dict[str, Any]] | None = None, execution_mode: str = "real", config: ModelConfig | None = None) -> AnalysisResult:
    """「分析并提问」交互：一次调用、严格解析；失败不重试，交互步骤不入 runs 留档，错误信息不含凭据。

    config 显式传入（如界面自配的运行时设置）时直接使用，跳过内部 get_config；默认 None 保持现有行为。
    """
    if model_call is not None and execution_mode != "stub":
        raise ValueError("注入测试替身必须显式标记 execution_mode='stub'")
    if execution_mode == "stub" and model_call is None:
        raise ValueError("stub 模式须提供替身，不能调用真实模型")
    analysis_path = Path(root) / "src" / "qixu_advisor" / "prompts" / "analysis.txt"
    if not analysis_path.exists():
        raise ValueError(f"缺少分析提示文件：{analysis_path.relative_to(Path(root)).as_posix()}，请先补充 prompts/analysis.txt")
    system = analysis_path.read_text(encoding="utf-8")
    user = json.dumps({"conversation_history": conversation_history, "client_information": client_information or {}}, ensure_ascii=False)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    config = config if config is not None else get_config(root)
    if execution_mode == "real" and not config.api_key.get_secret_value().strip():
        raise ValueError("未配置 DEEPSEEK_API_KEY；未发起真实模型请求")
    caller = model_call or call_model
    try:
        response = caller(messages, config)
    except ModelCallError as exc:
        # ModelCallError 已经清洗，不含凭据。
        raise ValueError(f"对话分析失败：{exc}；未自动重试") from exc
    except Exception as exc:
        # 非预期适配器错误不带异常文本，防止其中包含环境凭据。
        raise ValueError(f"对话分析发生 {type(exc).__name__}；未自动重试") from exc
    try:
        payload = json.loads(response["raw_text"])
        return AnalysisResult.model_validate(payload)
    except (ValidationError, ValueError, TypeError, KeyError) as exc:
        raise ValueError("分析结果结构不合格：需要含 scenario（六场景之一）、current_need（非空）与 missing_questions（0–3 条非空）的 JSON；未重试") from exc
