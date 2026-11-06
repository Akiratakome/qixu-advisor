"""拍摄真实本地界面；不生成、模拟或填写人工评价。"""
from pathlib import Path
import json
import argparse

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "artifacts/submissions/initial-local/screenshots/application"
TARGET.mkdir(parents=True, exist_ok=True)
parser = argparse.ArgumentParser()
parser.add_argument("--label", default="after", choices=["before", "after"])
label = parser.parse_args().label

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel="msedge", headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1100}, device_scale_factor=1)
    page.goto("http://127.0.0.1:8501", wait_until="networkidle")
    page.get_by_role("button", name="生成三条候选", exact=True).wait_for()
    page.screenshot(path=str(TARGET / f"desktop-input-{label}.png"), full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    page.screenshot(path=str(TARGET / f"mobile-input-{label}.png"), full_page=True)
    page.set_viewport_size({"width": 1440, "height": 1100})
    page.get_by_role("button", name="生成三条候选", exact=True).click()
    page.get_by_text("需要补充资料", exact=True).wait_for()
    page.screenshot(path=str(TARGET / f"missing-input-{label}.png"), full_page=True)
    observed = {"url": page.url, "missing_input_visible": True,
                "purpose": "真实浏览器缺祝福缘由路径；未调用模型、未填写人评"}
    page.get_by_text("人工评价", exact=True).first.click()
    page.get_by_text("该运行暂无三条机器候选可供评价。", exact=True).wait_for()
    page.screenshot(path=str(TARGET / f"evaluation-awaiting-output-{label}.png"), full_page=True)
    observed["human_evaluation_pending_visible"] = True
    (TARGET / f"observations-{label}.json").write_text(json.dumps(observed, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(observed, ensure_ascii=False))
    browser.close()
