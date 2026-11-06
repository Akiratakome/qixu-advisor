"""整理本轮已获授权的离线交付；保留缺件，不生成假输出或假评分。"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from qixu_advisor.evaluation import export_outputs, freeze_plan, validate_freeze
from qixu_advisor.records import source_versions, timestamp

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "artifacts/submissions/initial-local"
EVIDENCE = PACKAGE / "evidence"
EVIDENCE.mkdir(parents=True, exist_ok=True)

# 正式输入全部保留，真实输出为空；失败单例另作为连接证据。
output_status = export_outputs(PACKAGE / "outputs.csv", root=ROOT)
freeze_id = "offline-v1"
freeze = ROOT / "artifacts/evaluations/freezes" / f"{freeze_id}.json"
if freeze.exists():
    validate_freeze(freeze_id, root=ROOT)
else:
    freeze_plan(freeze_id, root=ROOT)
shutil.copy2(freeze, EVIDENCE / "offline-freeze.json")
shutil.copytree(ROOT / "data", EVIDENCE / "dataset", dirs_exist_ok=True)
shutil.copytree(ROOT / "artifacts/runs/smoke-20261106",
                EVIDENCE / "runs/smoke-20261106", dirs_exist_ok=True)
evaluation_screenshots = PACKAGE / "screenshots/evaluation"
evaluation_screenshots.mkdir(parents=True, exist_ok=True)
shutil.copy2(PACKAGE / "screenshots/application/evaluation-awaiting-output-after.png",
             evaluation_screenshots / "awaiting-evaluation.png")

smoke_manifest = json.loads((EVIDENCE / "runs/smoke-20261106/manifest.json").read_text(encoding="utf-8"))
commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True)
version_info = {
    "prepared_at": timestamp(),
    "submission_id": "initial-local",
    "scope": "用户指定本轮离线版本；完整assignment尚待真实输出与人评",
    "implementation_commit": commit.stdout.strip() if commit.returncode == 0 else None,
    "implementation_versions": source_versions(ROOT),
    "dependency_lock_sha256": hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest(),
    "cases_version": json.loads((ROOT / "data/cases/manifest.json").read_text(encoding="utf-8"))["version"],
    "rubric_version": json.loads((ROOT / "data/cases/rubric.json").read_text(encoding="utf-8"))["version"],
    "freeze_id": freeze_id,
    "freeze_purpose": "本地离线版本快照；后续真实运行前需复核标准与配置",
    "real_runs": [{"run_id": "smoke-20261106", "case_ids": ["SMOKE-001"],
                   "api_calls": 1, "status": "technical_failure", "http_status": 402,
                   "candidates": 0, "original_manifest": smoke_manifest}],
    "formal_fifty_run_id": None,
    "real_generated_candidates": 0,
    "human_ratings": 0,
    "screenshots": {"application": "真实本地Edge页面", "evaluation": "仅待评状态，无评分", "ai_chats": "缺失待补"},
    "historical_limit": "首轮smoke在首次Git提交前执行；已保存输入、完整提示、事实、配置和源码摘要，但未单独归档当时完整源码，不能声称该旧源码已由Git完整复现。",
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
with (PACKAGE / "work-log.csv").open("w", encoding="utf-8-sig", newline="") as stream:
    writer = csv.writer(stream)
    writer.writerow(["Step", "What you did", "Input", "Output", "Tool or agent used", "Screenshots"])
    writer.writerows(steps)
shutil.copy2(ROOT / "WORK_LOG.md", PACKAGE / "work-log-detail.md")
print(json.dumps({"package": str(PACKAGE), "rows": output_status["rows"],
                  "real_candidates": 0, "human_ratings": 0, "freeze_id": freeze_id}, ensure_ascii=False))
