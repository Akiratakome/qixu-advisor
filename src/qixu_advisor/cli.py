"""本地命令入口；与界面共用生成和评价函数。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from qixu_advisor.evaluation import (
    ROOT, HumanCaseRating, batch_run, export_outputs, freeze_plan,
    save_human_rating, summarize_evaluation, validate_dataset,
)
from qixu_advisor.model import config_status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="qixu", description="栖序 QIXU 本地顾问助手")
    parser.add_argument("--root", type=Path, default=ROOT, help="项目根目录")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="检查模型配置（只显示状态，不显示密钥）")
    sub.add_parser("validate-data", help="检查 50 例、场景分布、家族划分及评分预期")
    freeze = sub.add_parser("freeze", help="真实正式运行前冻结代码、资料、量表与模型配置")
    freeze.add_argument("--freeze-id", required=True)
    batch = sub.add_parser("batch", help="真实模型批量生成，不自动重试")
    batch.add_argument("--split", choices=["diagnostic", "dev", "holdout", "all"], default="diagnostic")
    batch.add_argument("--run-id")
    batch.add_argument("--freeze-id")
    batch.add_argument("--parent-run-id", help="技术重跑所关联的原运行；原运行不会覆盖")
    export = sub.add_parser("export", help="严格八列 50 行；无运行时生成明确未完成的空输出表")
    export.add_argument("--run-id")
    export.add_argument("--output", required=True, type=Path)
    rate = sub.add_parser("rate", help="导入真实评价者填写的一例三候选评价 JSON")
    rate.add_argument("--evaluation-id", required=True)
    rate.add_argument("--file", required=True, type=Path)
    summary = sub.add_parser("summarize", help="汇总真人评分，未评与缺失保留在分母")
    summary.add_argument("--evaluation-id", required=True)
    summary.add_argument("--run-id", required=True)
    summary.add_argument("--rater", required=True)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        if args.command == "check":
            result = config_status(root)
        elif args.command == "validate-data":
            result = validate_dataset(root=root)
        elif args.command == "freeze":
            result = {"frozen": str(freeze_plan(args.freeze_id, root=root))}
        elif args.command == "batch":
            result = batch_run(args.split, root=root, run_id=args.run_id, freeze_id=args.freeze_id, parent_run_id=args.parent_run_id)
        elif args.command == "export":
            result = export_outputs(args.output, run_id=args.run_id, root=root)
        elif args.command == "rate":
            rating = HumanCaseRating.model_validate_json(args.file.read_text(encoding="utf-8"))
            result = {"saved": str(save_human_rating(args.evaluation_id, rating, root=root))}
        else:
            result = summarize_evaluation(args.evaluation_id, args.run_id, args.rater, root=root)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError) as exc:
        print(f"未完成：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
