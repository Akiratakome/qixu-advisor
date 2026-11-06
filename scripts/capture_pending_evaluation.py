"""拍摄真实正式运行的人评待办界面；不填写或提交评分。"""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "artifacts/submissions/initial-local/screenshots/evaluation"
TARGET.mkdir(parents=True, exist_ok=True)

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel="msedge", headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 3600}, device_scale_factor=1)
    page.goto("http://127.0.0.1:8501", wait_until="domcontentloaded")
    page.get_by_text("人工评价", exact=True).first.click()
    page.get_by_role("combobox", name="待评价运行", exact=True).click()
    page.get_by_role("option", name="formal-v1", exact=True).click()
    page.get_by_role("button", name="保存本例人工评价", exact=True).wait_for()
    expect(page.get_by_role("textbox", name="评价编号", exact=True)).to_have_value("eval-formal-v1")
    page.wait_for_timeout(600)
    page.screenshot(path=str(TARGET / "formal-awaiting-human.png"), full_page=True)
    rating_controls = page.get_by_role("combobox", name="可用性", exact=True).all() + page.get_by_role("combobox", name="严重错误检查", exact=True).all() + page.get_by_role("combobox", name="本组三条是否包含两种不同且合理的完整选择", exact=True).all()
    values = [control.input_value() for control in rating_controls]
    observed = {"run_id": "formal-v1", "ratings_submitted": 0,
        "rating_control_values": values, "rater_field": page.get_by_role("textbox", name="真实评价者标识", exact=True).input_value(),
        "purpose": "真实机器输出的人评待办界面；不是已完成人评的证据"}
    print(json.dumps(observed, ensure_ascii=False))
    assert values == ["未评"] * 7 and observed["rater_field"] == ""
    (TARGET / "formal-awaiting-human.json").write_text(json.dumps(observed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(observed, ensure_ascii=False))
    browser.close()
