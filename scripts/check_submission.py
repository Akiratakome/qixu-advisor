"""核对交付格式、机器原稿对应、证据链接及秘密排除，不把缺件标成完成。"""
from __future__ import annotations

import csv
import json
from pathlib import Path
import re
import subprocess
from xml.etree import ElementTree

from dotenv import dotenv_values
from PIL import Image

from qixu_advisor.evaluation import OUTPUT_COLUMNS
from qixu_advisor.records import timestamp

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "artifacts/submissions/initial-local"
errors = []
with (PACKAGE / "outputs.csv").open(encoding="utf-8-sig", newline="") as file:
    reader = csv.DictReader(file)
    rows = list(reader)
    if reader.fieldnames != OUTPUT_COLUMNS:
        errors.append("C项不是严格八列")
if len(rows) != 50 or len({r["Case ID"] for r in rows}) != 50:
    errors.append("C项不是50个唯一输入")
nonempty_outputs = sum(bool(row[f"Output {i}"].strip()) for row in rows for i in (1, 2, 3))
versions = json.loads((PACKAGE / "versions.json").read_text(encoding="utf-8"))
formal_run = versions.get("formal_fifty_run_id")
provenance = {r["case_id"]: r for r in json.loads((PACKAGE / "row-provenance.json").read_text(encoding="utf-8"))}
for row in rows:
    texts = [row[f"Output {i}"] for i in (1, 2, 3)]
    if not any(texts):
        continue
    row_run = provenance.get(row["Case ID"], {}).get("run_id", formal_run)
    path = PACKAGE / "evidence/runs" / str(row_run) / "cases" / row["Case ID"] / "result.json"
    if not path.exists():
        errors.append(f"{row['Case ID']} 输出没有对应机器原稿")
        continue
    machine = json.loads(path.read_text(encoding="utf-8"))
    if machine["status"] != "success" or machine.get("provenance", {}).get("execution_mode") != "real" or texts != [c["text"] for c in machine["candidates"]]:
        errors.append(f"{row['Case ID']} 导出不是本批真实机器原稿")
if nonempty_outputs != versions["real_generated_candidates"]:
    errors.append("版本清单的真实候选数与八列表格不一致")
with (PACKAGE / "work-log.csv").open(encoding="utf-8-sig", newline="") as file:
    reader = csv.reader(file)
    if next(reader) != ["Step", "What you did", "Input", "Output", "Tool or agent used", "Screenshots"]:
        errors.append("A项不是指定六列表头")

missing_links = []
for path in PACKAGE.rglob("*.md"):
    for target in re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
        if target.startswith(("https://", "http://", "#")):
            continue
        linked = path.parent / target.split("#")[0]
        if linked.resolve() == (PACKAGE / "verification.json").resolve():
            continue  # 本脚本完成时写入自身报告，首次检查不误报该自引用。
        if not linked.exists():
            missing_links.append(f"{path.name}: {target}")
if missing_links:
    errors.append("存在无法随包打开的链接")
images = []
for path in (PACKAGE / "screenshots").rglob("*.png"):
    with Image.open(path) as image:
        image.verify()
    images.append(path.relative_to(PACKAGE).as_posix())
ElementTree.parse(PACKAGE / "architecture.svg")

secret = dotenv_values(ROOT / ".env").get("DEEPSEEK_API_KEY", "")
tracked = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout.decode("utf-8").split("\0")
paths = {ROOT / p for p in tracked if p}
paths.update(p for p in PACKAGE.rglob("*") if p.is_file())
secret_hits = []
if secret:
    needle = secret.encode("utf-8")
    secret_hits = [p.relative_to(ROOT).as_posix() for p in paths if p.is_file() and needle in p.read_bytes()]
if secret_hits:
    errors.append("发现本地真实密钥泄漏，需要移除后再交付")
if ".env" in tracked:
    errors.append(".env被Git跟踪")
if len(list((ROOT / "docs").glob("*.md"))) != 2:
    errors.append("docs不再恰好两份报告")

result = {
    "checked_at": timestamp(), "package_integrity_checks_passed": not errors,
    "output_rows": len(rows), "output_columns": OUTPUT_COLUMNS,
    "real_candidates": nonempty_outputs, "human_ratings": 0,
    "images_opened": images, "missing_links": missing_links,
    "real_secret_detected_paths": secret_hits, "errors": errors,
    "full_assignment_complete": False,
    "remaining": ["A历史及本轮真实AI对话截图", "D的逐条真人评分及真实评价截图"]
        + ([f"C尚缺{150-nonempty_outputs}条真实机器候选"] if nonempty_outputs != 150 else []),
}
(PACKAGE / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, indent=2))
raise SystemExit(bool(errors))
