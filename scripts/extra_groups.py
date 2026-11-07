"""多轮与语言补充组的真实运行与独立导出。

不进入正式 50 例与八列 C；运行前必须校验冻结指纹，先生成运行级标准再调用模型。
用法（在项目根目录）：
  ./.venv/Scripts/python.exe -X utf8 scripts/extra_groups.py run --group multiturn --freeze-id formal-v4 [--run-id multiturn-s1]
  ./.venv/Scripts/python.exe -X utf8 scripts/extra_groups.py export --group language --run-id language-s1 --output-dir artifacts/submissions/formal-v2-20261107
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qixu_advisor.evaluation import validate_freeze  # noqa: E402
from qixu_advisor.generation import generate  # noqa: E402
from qixu_advisor.models import CaseSpec  # noqa: E402
from qixu_advisor.records import create_run, load_result, timestamp  # noqa: E402

GROUPS = {"multiturn", "language"}
COLUMNS = [
    "Case ID", "Scenario", "Client information", "Conversation history",
    "Product information", "Output 1", "Output 2", "Output 3",
]

CRITERIA = {
    "multiturn": {
        "schema": "criteria-v1",
        "criteria": [
            "三条候选结构合格：不同、非空、符合输出语言设置",
            "每条候选回应的是对话历史中客户最新一条消息",
            "沿用前文已确认的人物、预算、商品与活动事实，不重新询问已知信息",
            "历史中的顾问话术不是客户偏好，不得当作客户喜好使用",
            "不越过既有联系意愿；内部约束不进对客正文",
        ],
        "review_policy": "AI 审阅仅辅助定位，不代替真人评价",
    },
    "language": {
        "schema": "criteria-v1",
        "criteria": [
            "三条候选结构合格：不同、非空",
            "输出语言与写作设置一致（en 组为英文、zh 组含中文）",
            "商品规范名保留中文原文（青岚/暮光/雨白/砚泊），币种、规格、日期与时区不因语言改变",
            "输入语言不影响场景职责；收礼人与购买者区分保持不变",
            "英文自然度须由具备相应语言能力的人审阅，AI 审阅不代替",
        ],
        "review_policy": "AI 审阅仅辅助定位，不代替真人评价",
    },
}


def load_group_cases(group: str) -> list[CaseSpec]:
    path = ROOT / "data" / "cases" / f"{group}.jsonl"
    if not path.exists():
        raise ValueError(f"用例文件不存在：{path}")
    cases = [CaseSpec.model_validate_json(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    if not cases:
        raise ValueError(f"{group} 用例为空")
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError(f"{group} 存在重复 case_id")
    if any(case.model_dump().get("group") != group for case in cases):
        raise ValueError(f"{group} 用例缺少正确的顶层 group 标记")
    return cases


def run_group(group: str, freeze_id: str, run_id: str | None, case_ids: set[str] | None = None, parent_run_id: str | None = None) -> dict:
    validate_freeze(freeze_id, root=ROOT)
    cases = load_group_cases(group)
    if case_ids:
        selected = [case for case in cases if case.case_id in case_ids]
        missing = case_ids - {case.case_id for case in selected}
        if missing:
            raise ValueError(f"过滤的 case_id 不存在：{sorted(missing)}")
        cases = selected
    actual_id = create_run([case.case_id for case in cases], root=ROOT, run_id=run_id, execution_mode="real", parent_run_id=parent_run_id)
    run_dir = ROOT / "artifacts" / "runs" / actual_id
    criteria_path = run_dir / "group-criteria.json"
    if criteria_path.exists():
        raise ValueError("运行已存在标准文件，请使用新 run-id")
    criteria_path.write_text(json.dumps({"group": group, "freeze_id": freeze_id, "created_at": timestamp(), **CRITERIA[group]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    plan = {"group": group, "freeze_id": freeze_id, "case_ids": [case.case_id for case in cases],
            "case_specs": [case.model_dump(mode="json") for case in cases]}
    (run_dir / "group-plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    statuses: dict[str, int] = {}
    for case in cases:
        result = generate(case.request, actual_id, case.case_id, root=ROOT)
        statuses[result.status] = statuses.get(result.status, 0) + 1
    return {"run_id": actual_id, "group": group, "target_cases": len(cases), "statuses": statuses, "execution_mode": "real"}


def export_group(group: str, run_id: str, output_dir: Path) -> dict:
    run_dir = ROOT / "artifacts" / "runs" / run_id
    if not (run_dir / "group-plan.json").exists():
        raise ValueError(f"{run_id} 不是补充组运行（缺少 group-plan.json）")
    plan = json.loads((run_dir / "group-plan.json").read_text(encoding="utf-8"))
    if plan.get("group") != group:
        raise ValueError(f"{run_id} 属于 {plan.get('group')}，与导出组 {group} 不一致")
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{group}-outputs-{run_id}.csv"
    missing = []
    successful = 0
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS)
        writer.writeheader()
        for case_id in plan["case_ids"]:
            case_dir = run_dir / "cases" / case_id
            snapshot = json.loads((case_dir / "input.json").read_text(encoding="utf-8"))
            request = snapshot["request"]
            facts = snapshot["facts"]
            texts = ["", "", ""]
            reason = "尚未生成"
            if (case_dir / "result.json").exists():
                result = load_result(run_id, case_id, root=ROOT)
                if result.status == "success" and len(result.candidates) == 3:
                    texts = [candidate.text for candidate in result.candidates]
                    successful += 1
                else:
                    reason = result.error or result.status
            if not all(texts):
                missing.append({"case_id": case_id, "reason": reason})
            product_info = {key: value for key, value in facts.items() if key not in {"client", "customer", "client_information", "customer_profile"}}
            writer.writerow(dict(zip(COLUMNS, [
                case_id, request["scenario"],
                json.dumps({"client_id": request.get("client_id"), "customer_profile": facts.get("customer_profile"), "client_information": request.get("client_information", {}), "occasion": request.get("occasion")}, ensure_ascii=False),
                json.dumps(request.get("conversation_history", []), ensure_ascii=False),
                json.dumps(product_info, ensure_ascii=False), *texts,
            ])))
    status = {"run_id": run_id, "group": group, "rows": len(plan["case_ids"]), "successful_cases": successful,
              "complete": not missing, "missing": missing, "source": "result.json 的机器候选；未使用 feedback.jsonl", "columns": COLUMNS}
    (output.with_suffix(".status.json")).write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="extra_groups", description="多轮与语言补充组运行与导出")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--group", choices=sorted(GROUPS), required=True)
    run.add_argument("--freeze-id", required=True)
    run.add_argument("--run-id")
    run.add_argument("--case-ids", help="可选：逗号分隔的 case_id 过滤（探针／复跑调试用）")
    run.add_argument("--parent-run-id", help="技术重跑所关联的原运行；原运行不会覆盖")
    export = sub.add_parser("export")
    export.add_argument("--group", choices=sorted(GROUPS), required=True)
    export.add_argument("--run-id", required=True)
    export.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            selected = {item.strip() for item in (args.case_ids or "").split(",") if item.strip()} or None
            result = run_group(args.group, args.freeze_id, args.run_id, selected, args.parent_run_id)
        else:
            result = export_group(args.group, args.run_id, args.output_dir.resolve())
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError) as exc:
        print(f"未完成：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
