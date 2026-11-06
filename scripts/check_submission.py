"""核对离线交付格式、证据链接、图片与秘密排除，不把缺件标成完成。"""
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
if nonempty_outputs:
    errors.append("本轮已指定离线交付，不应存在未经真实运行的候选")
with (PACKAGE / "work-log.csv").open(encoding="utf-8-sig", newline="") as file:
    reader = csv.reader(file)
    if next(reader) != ["Step", "What you did", "Input", "Output", "Tool or agent used", "Screenshots"]:
        errors.append("A项不是指定六列表头")

missing_links = []
for path in PACKAGE.glob("*.md"):
    for target in re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
        if target.startswith(("https://", "http://", "#")):
            continue
        if not (path.parent / target.split("#")[0]).exists():
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
    "checked_at": timestamp(), "offline_package_checks_passed": not errors,
    "output_rows": len(rows), "output_columns": OUTPUT_COLUMNS,
    "real_candidates": nonempty_outputs, "human_ratings": 0,
    "images_opened": images, "missing_links": missing_links,
    "real_secret_detected_paths": secret_hits, "errors": errors,
    "full_assignment_complete": False,
    "remaining": ["A历史及本轮真实AI对话截图", "C的150条真实机器候选",
                  "D的逐条真人评分及真实评价截图", "根据真实结果补充内容缺陷和版本对照"],
}
(PACKAGE / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, indent=2))
raise SystemExit(bool(errors))
