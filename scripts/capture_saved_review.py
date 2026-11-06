"""复核既有真实输出的编辑保存；不调用 API、不冒充新生成或真人评分。"""

import hashlib
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "run-20261106T080044-fcfb87ee"
CASE = ROOT / "artifacts/runs" / RUN_ID / "cases/UI-001"
TARGET = ROOT / "artifacts/submissions/initial-local/screenshots/application"
result_bytes = (CASE / "result.json").read_bytes()
result = json.loads(result_bytes)
original = result["candidates"][1]["text"]
prior_feedback = (CASE / "feedback.jsonl").read_text(encoding="utf-8").splitlines()
prior_attempts = (CASE / "attempts.jsonl").read_bytes()

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel="msedge", headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 2600}, device_scale_factor=1)
    page.goto("http://127.0.0.1:8502", wait_until="domcontentloaded")
    page.get_by_text("候选 2", exact=True).last.click()
    draft = page.get_by_role("textbox", name="编辑稿", exact=True)
    expect(draft).to_have_value(original)
    page.screenshot(path=str(TARGET / "real-saved-result-review-before-edit.png"), full_page=True)
    edited = original + "您方便时再回复我就好。"
    draft.fill(edited)
    expect(draft).to_have_value(edited)
    page.get_by_role("textbox", name="顾问标识（可选，与客户分开记录）", exact=True).fill("Codex界面验证（非真人评价）")
    page.get_by_role("button", name="保存处理记录", exact=True).click()
    page.get_by_text("处理记录已保存；机器原稿保持原样。", exact=True).wait_for()
    feedback = [json.loads(line) for line in (CASE / "feedback.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(feedback) == len(prior_feedback) + 1
    assert feedback[-1]["edited_text"] == edited
    assert feedback[-1]["operator"] == "Codex界面验证（非真人评价）"
    assert (CASE / "result.json").read_bytes() == result_bytes
    assert (CASE / "attempts.jsonl").read_bytes() == prior_attempts
    page.screenshot(path=str(TARGET / "real-saved-result-review-after-edit.png"), full_page=True)
    observed = {"run_id": RUN_ID, "case_id": "UI-001", "replayed_existing_result": True,
        "new_model_calls": 0, "human_ratings_written": 0, "feedback_records_before": len(prior_feedback),
        "feedback_records_after": len(feedback), "candidate_id": feedback[-1]["candidate_id"],
        "feedback_action": feedback[-1]["action"], "feedback_operator": feedback[-1]["operator"], "sent": feedback[-1]["sent"],
        "edited_text_differs_from_machine": edited != original, "machine_result_unchanged": True,
        "original_result_sha256": hashlib.sha256(result_bytes).hexdigest(),
        "purpose": "使用临时验证页面复用advisor_page；加载先前已保存真实结果，验证编辑追加保存"}
    (TARGET / "real-saved-result-review.json").write_text(json.dumps(observed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(observed, ensure_ascii=False))
    browser.close()
