"""批量、八列导出与真实人工评分；评分预期永远不进入生成函数。"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from qixu_advisor.data import contact_is_blocked, load_cases, load_facts, required_information
from qixu_advisor.generation import generate
from qixu_advisor.models import CaseSpec, SCENARIOS, valid_id
from qixu_advisor.records import create_run, load_result

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_COLUMNS = [
    "Case ID", "Scenario", "Client information", "Conversation history",
    "Product information", "Output 1", "Output 2", "Output 3",
]
DECISIONS = ("直接用", "小改可用", "实质改写", "弃用")


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _safe_id(value: str) -> str:
    return valid_id(value)


def _cases(root: Path) -> list:
    return load_cases("dev", root=root) + load_cases("holdout", root=root)


def _manifest(root: Path) -> dict:
    return _read(root / "data/cases/manifest.json")


def load_run_plan(run_id: str | None, *, root: Path = ROOT) -> dict:
    if run_id:
        path = root / "artifacts/runs" / _safe_id(run_id) / "evaluation-plan.json"
        if path.exists():
            return _read(path)
    return {}


def _has_case_snapshot(plan: dict) -> bool:
    return all(key in plan for key in ("case_specs", "case_manifest", "case_facts", "expectations", "rubric_snapshot"))


def _planned_cases(plan: dict, root: Path) -> list:
    return [CaseSpec.model_validate(item) for item in plan["case_specs"]] if _has_case_snapshot(plan) else _cases(root)


def plan_fingerprint(root: Path = ROOT) -> dict:
    """冻结内容与参数，不把凭据纳入文件或散列。"""
    from qixu_advisor.model import get_config, public_config

    files = sorted(
        p for directory in (root / "src/qixu_advisor", root / "data")
        for p in directory.rglob("*")
        if p.is_file() and p.suffix in {".py", ".txt", ".json", ".jsonl", ".md"}
    )
    hashes = {str(p.relative_to(root)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    return {
        "files": hashes,
        "model": public_config(get_config(root)),
    }


def freeze_plan(freeze_id: str, *, root: Path = ROOT) -> Path:
    path = root / "artifacts/evaluations/freezes" / f"{_safe_id(freeze_id)}.json"
    if path.exists():
        raise ValueError("该冻结编号已存在；请保留原记录，使用新编号。")
    validate_dataset(root=root)
    _write(path, {"freeze_id": freeze_id, "created_at": datetime.now(timezone.utc).isoformat(), **plan_fingerprint(root)})
    return path


def validate_freeze(freeze_id: str, *, root: Path = ROOT) -> dict:
    frozen = _read(root / "artifacts/evaluations/freezes" / f"{_safe_id(freeze_id)}.json")
    current = plan_fingerprint(root)
    if any(frozen.get(k) != current[k] for k in current):
        raise ValueError("代码、提示、资料、量表或模型配置在冻结后发生变化；请核对后建立新冻结版本。")
    return frozen


def validate_dataset(*, root: Path = ROOT) -> dict:
    cases = _cases(root)
    manifest = _manifest(root)
    expected_counts = {
        "dev": dict(zip(SCENARIOS, (3, 4, 3, 3, 3, 4))),
        "holdout": dict(zip(SCENARIOS, (5, 6, 5, 5, 3, 6))),
    }
    ids = [c.case_id for c in cases]
    if len(ids) != 50 or len(set(ids)) != 50:
        raise ValueError("正式源例应为 50 个不重复的 case_id。")
    listed = [c["case_id"] for c in manifest["cases"]]
    if len(listed) != 50 or set(listed) != set(ids):
        raise ValueError("案例清单与源例不一致。")
    families: dict[str, str] = {}
    counts: dict = {}
    for split in ("dev", "holdout"):
        selected = [c for c in cases if c.split == split]
        counts[split] = dict(Counter(c.request.scenario for c in selected))
        if counts[split] != expected_counts[split]:
            raise ValueError(f"{split} 场景分配不符合既定方案：{counts[split]}")
        for case in selected:
            if case.family_id in families and families[case.family_id] != split:
                raise ValueError(f"同源家族跨开发和保留集：{case.family_id}")
            families[case.family_id] = split
            facts = load_facts(case.request, root=root)
            missing = required_information(case.request, facts)
            if missing or contact_is_blocked(case.request, facts):
                raise ValueError(f"正式案例 {case.case_id} 无法生成（边界例应放 boundary）：{missing or '明确拒绝联系'}")
    expectations = [json.loads(line) for line in (root / "data/cases/expectations.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(expectations) != 50 or {e["case_id"] for e in expectations} != set(ids):
        raise ValueError("每个正式案例必须有且只有一份评分预期。")
    for expectation in expectations:
        if not 1 <= len(expectation["must_respond"]) <= 3 or not expectation["must_not"]:
            raise ValueError(f"评价要点不足或过多：{expectation['case_id']}")
    diagnostic = manifest["diagnostic_case_ids"]
    selected = [c for c in cases if c.case_id in diagnostic]
    if len(diagnostic) != 6 or len(selected) != 6 or any(c.split != "dev" for c in selected) or {c.request.scenario for c in selected} != set(SCENARIOS):
        raise ValueError("六个诊断例应从开发集每场景各取一个。")
    return {"valid": True, "cases": 50, "counts": counts, "diagnostic_case_ids": diagnostic, "human_ratings": "未由数据校验推断"}


def batch_run(split: str, *, root: Path = ROOT, run_id: str | None = None,
              freeze_id: str | None = None, parent_run_id: str | None = None) -> dict:
    from qixu_advisor.model import config_status

    if split not in {"diagnostic", "dev", "holdout", "all"}:
        raise ValueError("未知批次。")
    if not config_status(root)["configured"]:
        raise ValueError("模型配置不完整；请在本地 .env 补齐配置后再真实运行。")
    if split in {"holdout", "all"}:
        if not freeze_id:
            raise ValueError("保留集或正式全量运行需要 --freeze-id；先固定代码、资料、量表和模型。")
        validate_freeze(freeze_id, root=root)
    all_cases = _cases(root)
    cases = all_cases
    if split == "diagnostic":
        ids = set(_manifest(root)["diagnostic_case_ids"])
        cases = [c for c in cases if c.case_id in ids]
    elif split != "all":
        cases = [c for c in cases if c.split == split]
    holdout_ids = {c.case_id for c in all_cases if c.split == "holdout"}
    previous_holdout_runs = []
    for previous in (root / "artifacts/runs").glob("*/manifest.json"):
        prior = _read(previous)
        if prior.get("execution_mode") == "real" and any(
            (previous.parent / "cases" / case_id / "result.json").exists()
            for case_id in set(prior.get("case_ids", [])) & holdout_ids
        ):
            previous_holdout_runs.append(previous.parent.name)
    actual_id = create_run([c.case_id for c in cases], root=root, run_id=run_id,
                           execution_mode="real", parent_run_id=parent_run_id)
    _write(root / "artifacts/runs" / actual_id / "evaluation-plan.json", {
        "split": split, "freeze_id": freeze_id,
        "case_ids": [c.case_id for c in cases],
        "holdout_interpretation": ("回归验证：此前已有保留集结果" if previous_holdout_runs else "首次冻结运行；看过结果后的改动须标为回归验证") if split in {"holdout", "all"} else "开发诊断，不报告保留集成绩",
        "previous_holdout_runs": sorted(previous_holdout_runs),
        "rubric_snapshot": _read(root / "data/cases/rubric.json"),
        "expectations_sha256": hashlib.sha256((root / "data/cases/expectations.jsonl").read_bytes()).hexdigest(),
        "case_specs": [c.model_dump(mode="json") for c in all_cases],
        "case_manifest": _manifest(root),
        "case_facts": {c.case_id: load_facts(c.request, root=root) for c in all_cases},
        "expectations": [json.loads(line) for line in (root / "data/cases/expectations.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()],
    })
    statuses = Counter()
    for case in cases:
        result = generate(case.request, actual_id, case.case_id, root=root)
        statuses[result.status] += 1
    return {"run_id": actual_id, "target_cases": len(cases), "statuses": dict(statuses), "execution_mode": "real"}


def export_outputs(output: Path, *, run_id: str | None = None, root: Path = ROOT) -> dict:
    """固定五十行；缺失保留空单元格并另存清单，绝不拿编辑稿或替身填满。"""
    plan = load_run_plan(run_id, root=root)
    has_snapshot = _has_case_snapshot(plan)
    cases = _planned_cases(plan, root)
    case_manifest = plan["case_manifest"] if has_snapshot else _manifest(root)
    order = [c["case_id"] for c in case_manifest["cases"]]
    by_id = {c.case_id: c for c in cases}
    run_dir = None
    if run_id:
        run_dir = root / "artifacts/runs" / _safe_id(run_id)
        run = _read(run_dir / "manifest.json")
        if run.get("execution_mode") != "real":
            raise ValueError("替身运行不能导出为正式机器输出。")
    output.parent.mkdir(parents=True, exist_ok=True)
    missing = []
    successful = 0
    with output.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        for case_id in order:
            case = by_id[case_id]
            request = case.request.model_dump(mode="json")
            facts = plan["case_facts"][case_id] if has_snapshot else load_facts(case.request, root=root)
            texts = ["", "", ""]
            reason = "尚未真实运行" if has_snapshot or not run_id else "此历史运行未保存固定50例评价快照；不能填作正式50例结果"
            if has_snapshot and run_dir and (run_dir / "cases" / case_id / "input.json").exists():
                snapshot = _read(run_dir / "cases" / case_id / "input.json")
                request = snapshot.get("request", request)
                facts = snapshot.get("facts", facts)
            if has_snapshot and run_dir and (run_dir / "cases" / case_id / "result.json").exists():
                result = load_result(run_id, case_id, root=root)
                if result.provenance.get("execution_mode") != "real":
                    raise ValueError(f"{case_id} 结果缺少真实运行标记，不能导出为正式机器输出。")
                if result.status == "success" and len(result.candidates) == 3:
                    texts = [c.text for c in result.candidates]
                    successful += 1
                else:
                    reason = result.error or result.status
            if not all(texts):
                missing.append({"case_id": case_id, "reason": reason})
            # 政策与活动是生成所用业务资料，放在既定的 Product information 内，不添加第九列。
            product_info = {k: v for k, v in facts.items() if k not in {"client", "customer", "client_information", "customer_profile"}}
            writer.writerow(dict(zip(OUTPUT_COLUMNS, [
                case_id, request["scenario"],
                json.dumps({"client_id": request.get("client_id"), "customer_profile": facts.get("customer_profile"), "client_information": request.get("client_information", {}), "occasion": request.get("occasion")}, ensure_ascii=False),
                json.dumps(request.get("conversation_history", []), ensure_ascii=False),
                json.dumps(product_info, ensure_ascii=False), *texts,
            ])))
    status = {"run_id": run_id, "rows": len(order), "successful_cases": successful,
              "real_candidates": successful * 3, "complete": has_snapshot and len(order) == 50 and not missing,
              "snapshot_status": "运行时固定50例快照" if has_snapshot else "无历史评价快照；当前清单仅用于未完成的准备表",
              "missing": missing, "source": "result.json 的机器候选；未使用 feedback.jsonl", "columns": OUTPUT_COLUMNS}
    _write(output.with_suffix(".status.json"), status)
    return status


class CandidateRating(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: str
    decision: Literal["直接用", "小改可用", "实质改写", "弃用"]
    serious_error: bool
    reason: str = Field(min_length=1)
    edited_text: str = ""
    edit_seconds: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def check_error(self):
        if self.serious_error and self.decision in {"直接用", "小改可用"}:
            raise ValueError("人物、金额、规格或越权承诺等严重错误不能评为直接用或小改可用。")
        return self


class HumanCaseRating(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    case_id: str
    rater: str = Field(min_length=1)
    rater_role: Literal["开发者自评", "独立复核"]
    human_confirmed: Literal[True]
    candidates: list[CandidateRating] = Field(min_length=3, max_length=3)
    two_distinct_usable: bool
    diversity_reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def distinct(self):
        if len({c.candidate_id for c in self.candidates}) != 3:
            raise ValueError("三条评分必须关联不同候选。")
        usable = [c for c in self.candidates if c.decision in {"直接用", "小改可用"} and not c.serious_error]
        if self.two_distinct_usable and len(usable) < 2:
            raise ValueError("至少两条候选可用，才能判断有两种合理完整选择。")
        if not self.rater.strip() or not self.diversity_reason.strip() or any(not c.reason.strip() for c in self.candidates):
            raise ValueError("评价人和判断理由不能为空。")
        return self


def _run_rubric(run_id: str, root: Path) -> dict:
    plan = load_run_plan(run_id, root=root)
    if "rubric_snapshot" in plan:
        return plan["rubric_snapshot"]
    return _read(root / "data/cases/rubric.json")


def _rubric_digest(rubric: dict) -> str:
    return hashlib.sha256(json.dumps(rubric, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def save_human_rating(evaluation_id: str, rating: HumanCaseRating, *, root: Path = ROOT) -> Path:
    evaluation_id = _safe_id(evaluation_id)
    run_id, case_id = _safe_id(rating.run_id), _safe_id(rating.case_id)
    run = _read(root / "artifacts/runs" / run_id / "manifest.json")
    if run.get("execution_mode") != "real":
        raise ValueError("正式人评只接受真实模型运行；替身测试单独报告。")
    result = load_result(run_id, case_id, root=root)
    if result.status != "success" or {c.candidate_id for c in rating.candidates} != {c.candidate_id for c in result.candidates}:
        raise ValueError("评分与原始机器候选不一致。")
    target = root / "artifacts/evaluations" / evaluation_id / "ratings.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    rubric = _run_rubric(run_id, root)
    existing = [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines() if line.strip()] if target.exists() else []
    if any(row["run_id"] != run_id for row in existing):
        raise ValueError("一个评价编号只对应一个运行，不能混合批次成绩。")
    if any(row.get("rubric_sha256") != _rubric_digest(rubric) for row in existing):
        raise ValueError("本次量表与该评价编号既有评分不一致，不能混合口径。")
    revision = 1 + sum(row["case_id"] == case_id and row["rater"] == rating.rater for row in existing)
    record = {**rating.model_dump(), "rating_source": "human", "rubric_version": rubric["version"], "rubric_sha256": _rubric_digest(rubric),
              "created_at": datetime.now(timezone.utc).isoformat(), "revision": revision,
              "result_sha256": hashlib.sha256((root / "artifacts/runs" / run_id / "cases" / case_id / "result.json").read_bytes()).hexdigest()}
    with target.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return target


def summarize_evaluation(evaluation_id: str, run_id: str, rater: str, *, root: Path = ROOT) -> dict:
    evaluation_id, run_id = _safe_id(evaluation_id), _safe_id(run_id)
    run = _read(root / "artifacts/runs" / run_id / "manifest.json")
    if run.get("execution_mode") != "real":
        raise ValueError("正式评价汇总不接受替身运行。")
    base = root / "artifacts/evaluations" / evaluation_id
    rows = [json.loads(line) for line in (base / "ratings.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()] if (base / "ratings.jsonl").exists() else []
    selected = [r for r in rows if r["run_id"] == run_id and r["rater"] == rater and r.get("rating_source") == "human"]
    rubric = _run_rubric(run_id, root)
    plan = load_run_plan(run_id, root=root)
    has_snapshot = _has_case_snapshot(plan)
    cases = _planned_cases(plan, root)
    ids = {c.case_id for c in cases}
    for rating in selected:
        result_path = root / "artifacts/runs" / run_id / "cases" / _safe_id(rating["case_id"]) / "result.json"
        if rating.get("result_sha256") != hashlib.sha256(result_path.read_bytes()).hexdigest():
            raise ValueError(f"{rating['case_id']} 原始结果已变化，不能沿用旧评分。")
        if rating.get("rubric_version") != rubric["version"] or rating.get("rubric_sha256") != _rubric_digest(rubric):
            raise ValueError("评分量表与本运行量表不一致，不能合并。")
    latest = {r["case_id"]: r for r in selected if r["case_id"] in ids} if has_snapshot else {}
    summary = {"run_id": run_id, "rater": rater, "rating_source": "human", "rubric_version": rubric["version"],
               "rating_records": len(selected), "reviewed_cases": len(latest), "reviewed_candidates": 3 * len(latest),
               "snapshot_status": "运行时固定50例快照" if has_snapshot else "缺少历史评价快照；不能据当前源例归类为正式50例评价",
               "standalone_reviewed_cases": len({r["case_id"] for r in selected}) if not has_snapshot else 0,
               "rater_role": sorted({r["rater_role"] for r in latest.values()}), "splits": {}}
    for split in ("dev", "holdout"):
        split_cases = [c for c in cases if c.split == split]
        groups = {"全部": split_cases, **{s: [c for c in split_cases if c.request.scenario == s] for s in SCENARIOS}}
        summary["splits"][split] = {}
        for label, group in groups.items():
            counts = Counter({d: 0 for d in DECISIONS})
            reviewed = usable = diverse = severe = generated = 0
            failures = Counter()
            for case in group:
                path = root / "artifacts/runs" / run_id / "cases" / case.case_id / "result.json"
                if has_snapshot and path.exists():
                    status = _read(path)["status"]
                    if status == "success":
                        generated += 1
                    else:
                        failures[status] += 1
                else:
                    failures["missing"] += 1
                rating = latest.get(case.case_id)
                if not rating:
                    continue
                reviewed += 1
                usable += any(c["decision"] in {"直接用", "小改可用"} and not c["serious_error"] for c in rating["candidates"])
                diverse += rating["two_distinct_usable"]
                severe += sum(c["serious_error"] for c in rating["candidates"])
                counts.update(c["decision"] for c in rating["candidates"])
            summary["splits"][split][label] = {"denominator": len(group), "generated_cases": generated,
                "reviewed_cases": reviewed, "unreviewed_cases": len(group) - reviewed,
                "usable_cases": usable, "diverse_cases": diverse, "serious_error_candidates": severe,
                "reviewed_candidates": reviewed * 3, "decisions": dict(counts), "failures": dict(failures)}
    hold = summary["splits"]["holdout"]["全部"]
    dev = summary["splits"]["dev"]["全部"]
    complete = has_snapshot and dev["generated_cases"] == 20 and hold["generated_cases"] == 30 and len(latest) == 50
    thresholds = rubric["thresholds"]
    minimums = {s: thresholds["by_scenario"][s]["usable"] for s in SCENARIOS}
    summary["acceptance"] = {
        "complete": complete,
        "content_passed": complete and hold["usable_cases"] >= thresholds["holdout_usable"] and hold["diverse_cases"] >= thresholds["holdout_diverse"]
            and sum(s["全部"]["serious_error_candidates"] for s in summary["splits"].values()) == 0
            and all(summary["splits"]["holdout"][s]["usable_cases"] >= n for s, n in minimums.items()),
        "independent_review": "需另核对预先抽取的 12 例第二位真人评分与分歧；本汇总不自动认定独立验证",
    }
    summary["limitations"] = ["未评或缺失案例保留在固定分母中", "严重错误分母为实际审阅候选，缺失不算零错误", "本摘要使用该评价者最新修订；原评分仍保留", "合成案例结果不能推断真实客户转化或系统零风险"]
    _write(base / "summary.json", summary)
    return summary
