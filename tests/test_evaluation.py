"""只检验程序规则。所有伪造响应与评分均在 pytest 临时目录，不是模型或人评证据。"""

import csv
import json
import shutil
from pathlib import Path

import pytest

from qixu_advisor.evaluation import (
    ROOT, OUTPUT_COLUMNS, CandidateRating, HumanCaseRating, batch_run, export_outputs,
    save_human_rating, summarize_evaluation, validate_dataset,
)
from qixu_advisor.data import load_cases, load_facts
from qixu_advisor.models import GenerationResult


@pytest.fixture
def project(tmp_path):
    shutil.copytree(ROOT / "data", tmp_path / "data")
    shutil.copytree(ROOT / "src/qixu_advisor/prompts", tmp_path / "src/qixu_advisor/prompts")
    return tmp_path


def dump(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def fixture_record(project):
    """仅用于导出/评分软件测试的记录，不调用真实模型。"""
    base = project / "artifacts/runs/test-record"
    dump(base / "manifest.json", {"execution_mode": "real", "test_fixture_only": True})
    cases = load_cases("all", root=project)
    dump(base / "evaluation-plan.json", {
        "case_specs": [c.model_dump(mode="json") for c in cases],
        "case_manifest": json.loads((project / "data/cases/manifest.json").read_text(encoding="utf-8")),
        "case_facts": {c.case_id: load_facts(c.request, root=project) for c in cases},
        "expectations": [json.loads(line) for line in (project / "data/cases/expectations.jsonl").read_text(encoding="utf-8").splitlines()],
        "rubric_snapshot": json.loads((project / "data/cases/rubric.json").read_text(encoding="utf-8")),
    })
    dump(base / "cases/REC-001/result.json", {
        "run_id": "test-record", "case_id": "REC-001", "status": "success",
        "candidates": [{"candidate_id": f"REC-001-C{i}", "text": f"程序测试占位原稿{i}，不是模型质量证据。"} for i in (1, 2, 3)],
        "provenance": {"execution_mode": "real", "test_fixture_only": True},
    })
    dump(base / "cases/REC-001/feedback.jsonl", {"edited_text": "程序测试人工编辑占位，不能导出为机器输出"})
    return base


def rating():
    return HumanCaseRating(
        run_id="test-record", case_id="REC-001", rater="TEST-FIXTURE-ONLY", rater_role="开发者自评", human_confirmed=True,
        candidates=[CandidateRating(candidate_id=f"REC-001-C{i}", decision="直接用", serious_error=False, reason="程序测试占位判断，不是真人评分") for i in (1, 2, 3)],
        two_distinct_usable=True, diversity_reason="程序测试占位差异，不是真人评分",
    )


def test_fifty_rows_machine_outputs_and_no_feedback_leak(project):
    validate_dataset(root=project)
    fixture_record(project)
    out = project / "test-only.csv"
    status = export_outputs(out, run_id="test-record", root=project)
    with out.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        assert reader.fieldnames == OUTPUT_COLUMNS
    assert len(rows) == 50
    assert status["successful_cases"] == 1 and len(status["missing"]) == 49
    assert not status["complete"]
    rec = next(row for row in rows if row["Case ID"] == "REC-001")
    assert "测试占位原稿1" in rec["Output 1"]
    assert "人工编辑" not in out.read_text(encoding="utf-8-sig")


def test_export_refuses_stub_and_keeps_unrun_cases(project):
    dump(project / "artifacts/runs/test-stub/manifest.json", {"execution_mode": "stub"})
    with pytest.raises(ValueError, match="替身"):
        export_outputs(project / "test.csv", run_id="test-stub", root=project)
    status = export_outputs(project / "pending.csv", root=project)
    assert status["rows"] == 50 and status["real_candidates"] == 0
    assert len(status["missing"]) == 50


def test_ratings_append_missing_denominators_and_detect_changed_result(project):
    base = fixture_record(project)
    original = (base / "cases/REC-001/result.json").read_bytes()
    save_human_rating("test-eval", rating(), root=project)
    save_human_rating("test-eval", rating(), root=project)
    summary = summarize_evaluation("test-eval", "test-record", "TEST-FIXTURE-ONLY", root=project)
    assert summary["rating_records"] == 2 and summary["reviewed_candidates"] == 3
    assert summary["splits"]["holdout"]["全部"]["denominator"] == 30
    assert summary["splits"]["holdout"]["全部"]["unreviewed_cases"] == 30
    assert summary["splits"]["dev"]["全部"]["usable_cases"] == 1
    assert not summary["acceptance"]["content_passed"]
    assert (base / "cases/REC-001/result.json").read_bytes() == original
    (base / "cases/REC-001/result.json").write_bytes(original + b"\n")
    with pytest.raises(ValueError, match="原始结果已变化"):
        summarize_evaluation("test-eval", "test-record", "TEST-FIXTURE-ONLY", root=project)


def test_serious_errors_cannot_be_small_edit():
    with pytest.raises(ValueError, match="严重错误不能"):
        CandidateRating(candidate_id="C1", decision="小改可用", serious_error=True, reason="改一个错误价格")


def test_run_snapshot_survives_changed_cases_facts_expectations_and_rubric(project):
    fixture_record(project)
    before = project / "before.csv"
    export_outputs(before, run_id="test-record", root=project)
    save_human_rating("test-eval", rating(), root=project)
    dev_file = project / "data/cases/dev.jsonl"
    cases = [json.loads(line) for line in dev_file.read_text(encoding="utf-8").splitlines()]
    next(c for c in cases if c["case_id"] == "REC-001")["request"]["scenario"] = "生日与节庆"
    dev_file.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in cases), encoding="utf-8")
    products = project / "data/fictional/products.json"
    changed_products = json.loads(products.read_text(encoding="utf-8"))
    changed_products["records"][0]["price_cny"] = 1
    dump(products, changed_products)
    (project / "data/cases/expectations.jsonl").write_text("", encoding="utf-8")
    dump(project / "data/cases/rubric.json", {"version": "changed-rubric", "thresholds": {}})
    after = project / "after.csv"
    export_outputs(after, run_id="test-record", root=project)
    assert before.read_bytes() == after.read_bytes()
    summary = summarize_evaluation("test-eval", "test-record", "TEST-FIXTURE-ONLY", root=project)
    assert summary["splits"]["dev"]["产品推荐"]["usable_cases"] == 1
    assert summary["splits"]["dev"]["生日与节庆"]["usable_cases"] == 0
    assert summary["rubric_version"] != "changed-rubric"


def test_diagnostic_batch_freezes_full_fifty_case_context_without_network(project, monkeypatch):
    from qixu_advisor import evaluation, model

    called = []
    monkeypatch.setattr(model, "config_status", lambda root: {"configured": True})

    def offline_failure(request, run_id, case_id, *, root):
        called.append(case_id)
        return GenerationResult(run_id=run_id, case_id=case_id, status="technical_failure", error="仅程序测试，无网络调用")

    monkeypatch.setattr(evaluation, "generate", offline_failure)
    result = batch_run("diagnostic", root=project, run_id="test-batch")
    assert len(called) == 6 and result["statuses"] == {"technical_failure": 6}
    plan = json.loads((project / "artifacts/runs/test-batch/evaluation-plan.json").read_text(encoding="utf-8"))
    assert len(plan["case_specs"]) == len(plan["case_facts"]) == len(plan["expectations"]) == 50
    assert len(plan["case_ids"]) == 6
    assert "must_respond" not in json.dumps([c["request"] for c in plan["case_specs"]])
