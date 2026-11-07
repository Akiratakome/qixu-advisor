import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qixu_advisor.evaluation import OUTPUT_COLUMNS  # noqa: E402

run_dir = ROOT / "artifacts/runs/formal-v2"
manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
plan = json.loads((run_dir / "evaluation-plan.json").read_text(encoding="utf-8"))
order = [case["case_id"] for case in plan["case_manifest"]["cases"]]
rows = []
for case_id in order:
    case_dir = run_dir / "cases" / case_id
    result_path = case_dir / "result.json"
    input_path = case_dir / "input.json"
    entry = {
        "case_id": case_id,
        "input_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
        "result_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest() if result_path.exists() else None,
    }
    if result_path.exists():
        result = json.loads(result_path.read_text(encoding="utf-8"))
        entry["status"] = result["status"]
        entry["candidate_ids"] = [c["candidate_id"] for c in result.get("candidates", [])]
        entry["run_id"] = result["run_id"]
        entry["parent_run_id"] = manifest.get("parent_run_id")
    rows.append(entry)
out = {
    "run_id": "formal-v2",
    "freeze_id": plan.get("freeze_id"),
    "execution_mode": manifest.get("execution_mode"),
    "columns": OUTPUT_COLUMNS,
    "versions": manifest.get("versions"),
    "model_config": manifest.get("model_config"),
    "rows": rows,
}
target = ROOT / "artifacts/submissions/formal-v2-20261107/row-provenance.json"
target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

versions = {
    "submission_id": "formal-v2-20261107",
    "created_at": manifest.get("created_at"),
    "tool_versions": {
        "python": "3.12.15",
        "pydantic": "2.14.3",
        "streamlit": "1.67.0",
        "httpx": "0.28.1",
    },
    "runs": {
        "formal-v2": {"freeze": "formal-v2", "cases": 50, "statuses": "50 success", "role": "正式 C 表（50 例中文八列）"},
        "formal-v1": {"role": "回归基线（49/50＋关联技术重试）"},
        "diagnostic-s1": {"cases": 6, "role": "六场景开发诊断"},
        "multiturn-s2": {"cases": 6, "role": "多轮补充组首轮（5/6）＋ multiturn-s2-technical-retry（1 例）"},
        "language-s5": {"cases": 24, "role": "语言补充组首轮（22/24）＋ language-s5-technical-retry（2 例）"},
    },
    "freeze_ids": ["formal-v2", "formal-v3", "formal-v4", "formal-v5", "formal-v6", "formal-v7", "formal-v8", "formal-v9"],
    "git_commits": ["5df2dcf", "adb79b2", "bb82463", "77b5789", "7523aee", "08fdd7c", "bbd7c6a", "504ec9f", "b561019", "a1dd570", "b21de6d"],
}
(ROOT / "artifacts/submissions/formal-v2-20261107/versions.json").write_text(json.dumps(versions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("row-provenance rows:", len(rows), "| versions.json written")
