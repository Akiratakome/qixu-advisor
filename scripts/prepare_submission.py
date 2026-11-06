"""整理实际交付证据；保留缺件，不生成假输出或假评分。"""
from __future__ import annotations

import csv
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from qixu_advisor.evaluation import export_outputs, freeze_plan, validate_freeze, summarize_evaluation
from qixu_advisor.records import source_versions, timestamp

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "artifacts/submissions/initial-local"
EVIDENCE = PACKAGE / "evidence"
EVIDENCE.mkdir(parents=True, exist_ok=True)

parser = argparse.ArgumentParser()
parser.add_argument("--run-id")
parser.add_argument("--freeze-id", default="offline-v1")
parser.add_argument("--retry-run-id", help="只补首轮技术失败；首轮八列表格与统计另存，不合并成绩")
args = parser.parse_args()
# 正式输入全部保留；有指定批次时只导出该批机器原稿，缺失不删除。
output_status = export_outputs(PACKAGE / "outputs.csv", run_id=args.run_id, root=ROOT)
row_provenance = []
if args.run_id:
    for case in json.loads((ROOT / "data/cases/manifest.json").read_text(encoding="utf-8"))["cases"]:
        result_file = ROOT / "artifacts/runs" / args.run_id / "cases" / case["case_id"] / "result.json"
        result = json.loads(result_file.read_text(encoding="utf-8")) if result_file.exists() else {"status": "missing"}
        row_provenance.append({"case_id": case["case_id"], "run_id": args.run_id,
                               "first_run_id": args.run_id, "first_status": result["status"],
                               "selection_reason": "首次固定配置输出",
                               "result_sha256": hashlib.sha256(result_file.read_bytes()).hexdigest() if result_file.exists() else None})
if args.retry_run_id:
    if not args.run_id:
        raise ValueError("技术重试必须关联一个指定首轮运行")
    first_dir = ROOT / "artifacts/runs" / args.run_id
    retry_dir = ROOT / "artifacts/runs" / args.retry_run_id
    first_manifest = json.loads((first_dir / "manifest.json").read_text(encoding="utf-8"))
    retry_manifest = json.loads((retry_dir / "manifest.json").read_text(encoding="utf-8"))
    if retry_manifest.get("parent_run_id") != args.run_id or any(first_manifest[k] != retry_manifest[k] for k in ("versions", "model_config", "execution_mode")):
        raise ValueError("只能补充同源码、提示、事实、参数且显式关联首轮的技术重试")
    shutil.copy2(PACKAGE / "outputs.csv", PACKAGE / "outputs-first-attempt.csv")
    shutil.copy2(PACKAGE / "outputs.status.json", PACKAGE / "outputs-first-attempt.status.json")
    with (PACKAGE / "outputs.csv").open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        columns, rows = reader.fieldnames, list(reader)
    by_case = {row["Case ID"]: row for row in rows}
    by_origin = {row["case_id"]: row for row in row_provenance}
    for case_id in retry_manifest["case_ids"]:
        original = json.loads((first_dir / "cases" / case_id / "result.json").read_text(encoding="utf-8"))
        retry_file = retry_dir / "cases" / case_id / "result.json"
        retry = json.loads(retry_file.read_text(encoding="utf-8"))
        first_request = json.loads((first_dir / "cases" / case_id / "input.json").read_text(encoding="utf-8"))["request"]
        retry_request = json.loads((retry_dir / "cases" / case_id / "input.json").read_text(encoding="utf-8"))["request"]
        if original["status"] != "technical_failure" or first_request != retry_request:
            raise ValueError("不能挑选成功稿重抽后的结果，也不能替换输入")
        if retry["status"] == "success" and retry["provenance"]["execution_mode"] == "real":
            for i, candidate in enumerate(retry["candidates"], 1):
                by_case[case_id][f"Output {i}"] = candidate["text"]
            by_origin[case_id].update({"run_id": args.retry_run_id, "selection_reason": "首轮JSON格式失败后一次同配置技术重试；首轮统计不变",
                                       "result_sha256": hashlib.sha256(retry_file.read_bytes()).hexdigest()})
    with (PACKAGE / "outputs.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    missing = [{"case_id": row["Case ID"], "reason": "首轮或关联技术重试后仍缺少完整三条"} for row in rows if not all(row[f"Output {i}"] for i in (1, 2, 3))]
    output_status.update({"first_attempt_candidates": output_status["real_candidates"],
                          "successful_cases": len(rows) - len(missing), "real_candidates": 3 * (len(rows) - len(missing)),
                          "complete": len(rows) == 50 and not missing, "missing": missing,
                          "technical_retry_run_id": args.retry_run_id, "row_provenance": "row-provenance.json",
                          "interpretation": "最终交付表补入唯一技术重试；首轮表和首轮49/50统计独立保留"})
    (PACKAGE / "outputs.status.json").write_text(json.dumps(output_status, ensure_ascii=False, indent=2), encoding="utf-8")
(PACKAGE / "row-provenance.json").write_text(json.dumps(row_provenance, ensure_ascii=False, indent=2), encoding="utf-8")
freeze_id = args.freeze_id
freeze = ROOT / "artifacts/evaluations/freezes" / f"{freeze_id}.json"
if freeze.exists():
    validate_freeze(freeze_id, root=ROOT)
else:
    freeze_plan(freeze_id, root=ROOT)
shutil.copy2(freeze, EVIDENCE / "frozen-plan.json")
shutil.copytree(ROOT / "data", EVIDENCE / "dataset", dirs_exist_ok=True)
implementation = EVIDENCE / "implementation"
shutil.copytree(ROOT / "src", implementation / "src", dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
shutil.copytree(ROOT / "data/fictional", implementation / "data/fictional", dirs_exist_ok=True)
for filename in ("pyproject.toml", "uv.lock", ".python-version"):
    shutil.copy2(ROOT / filename, implementation / filename)
if source_versions(implementation) != source_versions(ROOT):
    raise ValueError("交付中的实现快照与运行源码／提示／事实字节不一致")
real_runs = []
for directory in sorted((ROOT / "artifacts/runs").iterdir()):
    manifest_file = directory / "manifest.json"
    if not manifest_file.exists():
        continue
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if manifest.get("execution_mode") != "real":
        continue
    shutil.copytree(directory, EVIDENCE / "runs" / directory.name, dirs_exist_ok=True)
    results = [json.loads(path.read_text(encoding="utf-8")) for path in directory.glob("cases/*/result.json")]
    real_runs.append({"run_id": directory.name, "case_ids": manifest["case_ids"],
                     "api_calls": sum(result.get("provenance", {}).get("model_call_count", 0) for result in results),
                     "statuses": dict(Counter(result["status"] for result in results)),
                     "candidates": sum(len(result["candidates"]) for result in results),
                     "original_manifest": manifest})
evaluation_screenshots = PACKAGE / "screenshots/evaluation"
evaluation_screenshots.mkdir(parents=True, exist_ok=True)
shutil.copy2(PACKAGE / "screenshots/application/evaluation-awaiting-output-after.png",
             evaluation_screenshots / "awaiting-evaluation.png")

commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True)
version_info = {
    "prepared_at": timestamp(),
    "submission_id": "initial-local",
    "scope": "本地应用与真实运行；人工评价和AI对话截图仍待补" if args.run_id else "离线准备；真实输出与人工评价待补",
    "implementation_commit": commit.stdout.strip() if commit.returncode == 0 else None,
    "implementation_versions": source_versions(ROOT),
    "exact_implementation_snapshot": "evidence/implementation/（保存运行时原始字节，避免Git换行转换影响摘要；案例资料另见evidence/dataset）",
    "dependency_lock_sha256": hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest(),
    "cases_version": json.loads((ROOT / "data/cases/manifest.json").read_text(encoding="utf-8"))["version"],
    "rubric_version": json.loads((ROOT / "data/cases/rubric.json").read_text(encoding="utf-8"))["version"],
    "freeze_id": freeze_id,
    "freeze_purpose": "正式运行前固定代码、提示、事实、案例、预期和量表",
    "real_runs": real_runs,
    "formal_fifty_run_id": args.run_id,
    "technical_retry_run_id": args.retry_run_id,
    "first_attempt_real_candidates": output_status.get("first_attempt_candidates", output_status["real_candidates"]),
    "real_generated_candidates": output_status["real_candidates"],
    "human_ratings": 0,
    "screenshots": {"application": "真实本地Edge页面", "evaluation": "仅待评状态，无评分", "ai_chats": "缺失待补"},
    "historical_limit": "最初HTTP402的smoke在首次Git提交前执行；已保存输入、完整提示、事实、配置和源码摘要，但未单独归档当时完整源码，不能声称该旧源码已由Git完整复现。其后基线对应5df2dcf，JSON约束版本对应adb79b2。",
}
(PACKAGE / "versions.json").write_text(json.dumps(version_info, ensure_ascii=False, indent=2), encoding="utf-8")

steps = [
    ["00", "本轮之前已有两份设计报告；原始历史未补造", "既有产品设计、技术报告", "沿用已授权方案；历史对话截图待补", "历史工具／完整步骤未核实", "待补：历史真实AI对话截图"],
    ["01", "读取项目约束、两报告、岗位要求及两页题目", "用户授权；AGENTS；两报告；本地附件", "核对六场景、A–E、严格表头和交付边界", "Codex主session；PowerShell；pypdf", "待补：本步真实AI对话截图"],
    ["02", "分配核心、数据、界面与评价任务；建立工作日志", "已有工程方案", "3个子agent明确职责与数据合同", "Codex主session与core/dataset/ui_eval", "待补：分工对话截图"],
    ["03", "安装锁定依赖并修复Windows启动器", "uv；Python3.12；pyproject", "标准venv启动器可运行；uv.lock", "PowerShell；uv；Python标准venv", "待补：本步AI对话截图；命令验证见evidence/offline-verification.json"],
    ["04", "核验实际API并实现共享生成与记录", "官方DeepSeek/Streamlit文档；既定模块合同", "输入、原始返回、机器稿、反馈分存；不自动重试", "Codex主session与core；官方文档", "待补：实现对话截图"],
    ["05", "实际执行一次DeepSeek生成", "本地凭据；SMOKE-001虚构推荐任务", "HTTP402失败，0候选；用户随后选择本轮离线交付", "DeepSeek API；共享generate", "待补：本步AI对话截图；原始记录见evidence/runs/smoke-20261106"],
    ["06", "制作事实和50例，实际定向核验四个ABCD源例", "合成业务设定；固定版本ABCD", "20dev/30holdout、4boundary、预期与rubric，来源及MIT声明", "dataset子agent；Python；官方GitHub数据", "待补：数据制作对话截图"],
    ["07", "完成表单、编辑、批量、冻结、八列导出和真人评价入口", "核心函数合同；PDF表头", "本地Streamlit与CLI共用生成函数", "ui_eval子agent；Streamlit/Pydantic", "screenshots/application/desktop-input.png（应用截图；AI对话仍待补）"],
    ["08", "运行离线检查与真实浏览器路径", "临时目录中的显式替身；真实本地应用", "测试记录与缺资料状态；未调用模型／填写人评", "pytest；Streamlit AppTest；Edge/Playwright", "screenshots/application/missing-input-after.png（应用截图；AI对话仍待补）"],
    ["09", "按de-slop截图清理表单与移动端布局", "桌面／手机实际截图", "顶部工作区；按场景显示字段；保留前后截图", "Codex主session；de-slop；ui_eval", "screenshots/application/mobile-input.png；screenshots/application/mobile-input-after.png；AI对话待补"],
    ["10", "独立代码复核并修复版本漂移和旧候选残留", "隔离替身复现；旧数据改场景后汇总错误", "运行时完整评价快照；失败清理旧结果；回归检查", "core与ui_eval子agent；pytest", "待补：复核AI对话截图；evidence/tests-final.txt为命令输出非截图"],
    ["11", "复核故事家族与购后状态并修订数据", "三个案例与对应评分要点", "cases-v1.1；保留真实修改前后片段", "dataset子agent；主session审阅", "待补：数据复核AI对话截图；evidence/data-before.json及data-after.json"],
    ["12", "最终离线验证、整理A–E及版本记录，初版Git提交", "当前代码／数据／真实失败／截图", "离线交付包；C真实输出与D真人评分明确待补", "Codex主session；pytest；Git", "待补：本步AI对话截图；待评界面见screenshots/evaluation/awaiting-evaluation.png"],
]
if args.run_id:
    steps += [
        ["13", "用户提供新凭据后重启真实验证", "新本地配置；原smoke相同输入", "smoke-recheck成功三候选，关联原HTTP402失败", "DeepSeek API；Codex主session", "待补：本步真实AI对话截图；原始结果见evidence/runs/smoke-recheck-20261106"],
        ["14", "六开发诊断，仅强化JSON格式做一次对照", "diagnostic-v1；同模型参数、事实、六输入", "v1结构5/6；v2结构6/6；保留原非法JSON，无人工质量评分", "DeepSeek API；core辅助审阅", "待补：对照AI聊天截图；evidence/ai-diagnostic-review.md"],
        ["15", "冻结后首次正式五十例真实运行", "formal-v1冻结清单；cases-v1.1；rubric-v1", f"outputs.csv包含{output_status['real_candidates']}条真实候选；失败与缺失见status", "共享批量生成；DeepSeek API", "待补：本步AI对话截图；原始记录见evidence/runs/formal-v1"],
        ["16", "实际浏览器生成、选稿与编辑验证；整理最终包", "新本地界面及真实候选", "机器稿与编辑稿分存；未填写真人评价", "ui_eval；Edge/Playwright；Git", "screenshots/application/real-three-candidates.png；real-saved-result-review-after-edit.png为既有结果复核，非新生成；AI对话待补"],
    ]
    if args.retry_run_id:
        steps.append(["17", "仅重试首轮JSON结构失败例并补全最终交付表", "AFTER-105相同输入和冻结配置", "一次关联重试成功；首轮147条表保留，最终150条逐行标来源", "DeepSeek API；主session；打包校验", "待补：本步AI对话截图；outputs-first-attempt.csv与row-provenance.json"])
with (PACKAGE / "work-log.csv").open("w", encoding="utf-8-sig", newline="") as stream:
    writer = csv.writer(stream)
    writer.writerow(["Step", "What you did", "Input", "Output", "Tool or agent used", "Screenshots"])
    writer.writerows(steps)
shutil.copy2(ROOT / "WORK_LOG.md", PACKAGE / "work-log-detail.md")
if args.run_id:
    summary = summarize_evaluation("pending-formal-v1", args.run_id, "尚无真人评价", root=ROOT)
    (EVIDENCE / "human-evaluation-pending.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"package": str(PACKAGE), "rows": output_status["rows"],
                  "real_candidates": output_status["real_candidates"], "human_ratings": 0, "freeze_id": freeze_id}, ensure_ascii=False))
