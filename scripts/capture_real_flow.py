"""用真实 Edge 验证一次选稿闭环；只点一次生成，不填写真人评分。"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "artifacts/submissions/initial-local/screenshots/application"
TARGET.mkdir(parents=True, exist_ok=True)
OBSERVATIONS = TARGET / "real-flow-observations.json"


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def ui_runs() -> set[str]:
    return {p.parent.name for p in (ROOT / "artifacts/runs").glob("*/manifest.json")
            if read(p).get("case_ids") == ["UI-001"]}


def ui_attempts() -> int:
    return sum(len([line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()])
               for path in (ROOT / "artifacts/runs").glob("*/cases/UI-001/attempts.jsonl"))


def save(observed: dict) -> None:
    OBSERVATIONS.write_text(json.dumps(observed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(observed, ensure_ascii=False), flush=True)


def main() -> int:
    if OBSERVATIONS.exists() and read(OBSERVATIONS).get("generation_button_clicks", 0):
        raise SystemExit("本验证已有一次生成点击记录；禁止自动重跑，以免再次调用模型。")
    observed = {"started_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "真实浏览器选稿和编辑验证；Codex 操作，不是真人评价", "generation_button_clicks": 0,
        "human_ratings_written": 0, "source_preset": "REC-001", "screenshots": []}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 2600}, device_scale_factor=1)
        try:
            page.goto("http://127.0.0.1:8501", wait_until="domcontentloaded")
            page.get_by_role("button", name="生成三条候选", exact=True).wait_for(timeout=60000)
            page.get_by_role("combobox", name="沟通场景").click()
            page.get_by_role("option", name="产品推荐", exact=True).click()
            page.get_by_text("开发案例", exact=True).click()
            page.get_by_role("combobox", name="选择案例").wait_for()
            # 产品推荐开发例的首项是 REC-001；显式检查，避免误用其他输入。
            preset = page.get_by_test_id("stSelectbox").filter(has=page.get_by_text("选择案例", exact=True))
            if "REC-001" not in preset.inner_text():
                preset.get_by_role("combobox").click()
                page.get_by_role("option", name="REC-001", exact=True).click()
            need = page.get_by_role("textbox", name="本次需求", exact=True)
            need.wait_for()
            original_need = need.input_value()
            before_runs, before_attempts = ui_runs(), ui_attempts()
            need.fill(original_need + "请保持简短。")
            need.fill(original_need)
            page.wait_for_timeout(800)
            observed["input_changes_created_runs"] = len(ui_runs() - before_runs)
            observed["input_changes_created_attempts"] = ui_attempts() - before_attempts
            assert observed["input_changes_created_runs"] == observed["input_changes_created_attempts"] == 0
            page.screenshot(path=str(TARGET / "real-before-generation.png"), full_page=True)
            observed["screenshots"].append("real-before-generation.png")
            observed["generation_button_clicks"] = 1
            page.get_by_role("button", name="生成三条候选", exact=True).click()
            save(observed)
            page.get_by_role("heading", name="本次结果", exact=True).wait_for(timeout=120000)
            new_runs = ui_runs() - before_runs
            assert len(new_runs) == 1, f"本次应新增一次 UI 运行，实际为 {len(new_runs)}"
            run_id = next(iter(new_runs))
            case_path = ROOT / "artifacts/runs" / run_id / "cases/UI-001"
            result_path = case_path / "result.json"
            result = read(result_path)
            observed.update({"run_id": run_id, "case_id": "UI-001", "status": result["status"],
                "candidate_count": len(result["candidates"]), "attempt_count": len((case_path / "attempts.jsonl").read_text(encoding="utf-8").splitlines())})
            if result["status"] != "success":
                page.screenshot(path=str(TARGET / "real-generation-failed.png"), full_page=True)
                observed["screenshots"].append("real-generation-failed.png")
                observed["error"] = result.get("error")
                save(observed)
                return 1
            assert len(result["candidates"]) == 3
            machine_bytes = result_path.read_bytes()
            observed["original_result_sha256"] = hashlib.sha256(machine_bytes).hexdigest()
            page.screenshot(path=str(TARGET / "real-three-candidates.png"), full_page=True)
            observed["screenshots"].append("real-three-candidates.png")
            page.get_by_text("候选 2", exact=True).last.click()
            draft = page.get_by_role("textbox", name="编辑稿", exact=True)
            expect(draft).to_have_value(result["candidates"][1]["text"])
            edited = draft.input_value() + "您方便时再回复我就好。"
            draft.fill(edited)
            page.get_by_role("textbox", name="顾问标识（可选，与客户分开记录）", exact=True).fill("Codex界面验证（非真人评价）")
            page.get_by_role("button", name="保存处理记录", exact=True).click()
            page.get_by_text("处理记录已保存；机器原稿保持原样。", exact=True).wait_for()
            page.screenshot(path=str(TARGET / "real-after-edit.png"), full_page=True)
            observed["screenshots"].append("real-after-edit.png")
            feedback = [json.loads(line) for line in (case_path / "feedback.jsonl").read_text(encoding="utf-8").splitlines()]
            assert len(feedback) == 1 and feedback[0]["action"] == "edit"
            assert feedback[0]["operator"] == "Codex界面验证（非真人评价）"
            assert feedback[0]["edited_text"] == edited
            assert result_path.read_bytes() == machine_bytes
            assert ui_attempts() - before_attempts == 1
            observed.update({"feedback_action": feedback[0]["action"], "candidate_id": feedback[0]["candidate_id"],
                "feedback_operator": feedback[0]["operator"], "sent": feedback[0]["sent"],
                "machine_result_unchanged": True, "total_new_ui_attempts": ui_attempts() - before_attempts,
                "completed_at": datetime.now(timezone.utc).isoformat()})
            save(observed)
            return 0
        except Exception as exc:
            observed["automation_error"] = f"{type(exc).__name__}: {exc}"
            page.screenshot(path=str(TARGET / "real-flow-error.png"), full_page=True)
            observed["screenshots"].append("real-flow-error.png")
            save(observed)
            return 1
        finally:
            browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
