"""执行离线检查并保存真实 stdout；本脚本不调用模型或填写人工评分。"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys

from qixu_advisor.evaluation import validate_dataset
from qixu_advisor.records import source_versions, timestamp

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "artifacts/submissions/initial-local/evidence"
DEST.mkdir(parents=True, exist_ok=True)

test = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=ROOT,
                      capture_output=True, encoding="utf-8", errors="replace")
(DEST / "tests-final.txt").write_text(test.stdout + test.stderr, encoding="utf-8")
report = {
    "checked_at": timestamp(),
    "kind": "offline_software_verification",
    "pytest_command": "python -m pytest -q",
    "pytest_exit_code": test.returncode,
    "pytest_stdout": test.stdout,
    "dataset": validate_dataset(root=ROOT),
    "versions": source_versions(ROOT),
    "lock_sha256": hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest(),
    "python": sys.version,
    "packages": {name: importlib.metadata.version(name) for name in
                 ["streamlit", "pydantic", "httpx", "python-dotenv", "pytest", "playwright"]},
    "limitations": ["测试替身及测试评分仅在临时目录，不是模型实测或人工评价",
                    "本脚本无模型网络调用，未生成正式候选"],
}
(DEST / "offline-verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(test.stdout, end="")
print(json.dumps(report["dataset"], ensure_ascii=False))
raise SystemExit(test.returncode)
