"""本地不可覆盖的机器记录和追加式人工反馈。"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .data import PROJECT_ROOT
from .model import get_config, public_config
from .models import GenerationResult, valid_id


def timestamp() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="milliseconds")


def write_json(path: Path, value: Any, *, overwrite: bool = False) -> None:
    with path.open("w" if overwrite else "x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def append_jsonl(path: Path, value: Any) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False) + "\n")


def source_versions(root: Path = PROJECT_ROOT) -> dict[str, str]:
    root = Path(root)

    def digest(paths: list[Path]) -> str:
        hashed = hashlib.sha256()
        for path in sorted(paths):
            hashed.update(path.relative_to(root).as_posix().encode("utf-8"))
            hashed.update(b"\0")
            hashed.update(path.read_bytes())
            hashed.update(b"\0")
        return hashed.hexdigest()

    source = root / "src" / "qixu_advisor"
    return {
        "code_sha256": digest(list(source.rglob("*.py"))),
        "prompt_sha256": digest([path for path in (source / "prompts").rglob("*") if path.is_file()]),
        "facts_sha256": digest(list((root / "data" / "fictional").glob("*.json"))),
    }


def run_directory(run_id: str, *, root: Path = PROJECT_ROOT) -> Path:
    return Path(root) / "artifacts" / "runs" / valid_id(run_id)


def case_directory(run_id: str, case_id: str, *, root: Path = PROJECT_ROOT) -> Path:
    return run_directory(run_id, root=root) / "cases" / valid_id(case_id)


def create_run(case_ids: list[str], *, root: Path = PROJECT_ROOT, run_id: str | None = None, execution_mode: str = "real", parent_run_id: str | None = None) -> str:
    if execution_mode not in {"real", "stub"}:
        raise ValueError("execution_mode 须为 real 或 stub")
    if len(case_ids) != len(set(case_ids)) or not case_ids:
        raise ValueError("运行清单必须非空且 case_id 不重复")
    for case_id in case_ids:
        valid_id(case_id)
    if parent_run_id:
        valid_id(parent_run_id)
        if not (run_directory(parent_run_id, root=root) / "manifest.json").exists():
            raise ValueError("原运行不存在，无法关联重跑")
    run_id = run_id or datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%S-") + uuid.uuid4().hex[:8]
    path = run_directory(run_id, root=root)
    path.mkdir(parents=True, exist_ok=False)
    try:
        configuration = public_config(get_config(root))
    except (ValueError, TypeError):
        configuration = {"configuration_error": "模型参数格式无效"}
    write_json(path / "manifest.json", {"schema_version": "1.0", "run_id": run_id, "created_at": timestamp(), "execution_mode": execution_mode, "parent_run_id": parent_run_id, "case_ids": case_ids, "model_config": configuration, "versions": source_versions(root), "first_attempt_policy": "每个案例只调用一次；再次尝试须创建关联的新运行", "quality_status": "not_human_evaluated"})
    return run_id


def begin_case(run_id: str, case_id: str, snapshot: dict[str, Any], *, root: Path = PROJECT_ROOT, execution_mode: str = "real") -> Path:
    manifest = read_json(run_directory(run_id, root=root) / "manifest.json")
    if case_id not in manifest["case_ids"]:
        raise ValueError("案例不在本次固定运行清单中")
    if manifest["execution_mode"] != execution_mode:
        raise ValueError("运行模式与生成模式不一致，不能混入替身结果")
    actual = snapshot.get("provenance", {})
    if manifest.get("versions") != actual.get("versions"):
        raise ValueError("源码、提示或事实在运行创建后发生变化，请创建新运行")
    if manifest.get("model_config") != actual.get("model_config"):
        raise ValueError("模型参数在运行创建后发生变化，请创建新运行")
    path = case_directory(run_id, case_id, root=root)
    # 先占用案例目录，再保存输入；重复操作不会覆盖首轮原稿。
    path.mkdir(parents=True, exist_ok=False)
    write_json(path / "input.json", snapshot)
    (path / "attempts.jsonl").touch(exist_ok=False)
    return path


def save_result(result: GenerationResult, *, root: Path = PROJECT_ROOT) -> Path:
    path = case_directory(result.run_id, result.case_id, root=root) / "result.json"
    write_json(path, result.model_dump(mode="json"))
    return path


def load_result(run_id: str, case_id: str, *, root: Path = PROJECT_ROOT) -> GenerationResult:
    return GenerationResult.model_validate(read_json(case_directory(run_id, case_id, root=root) / "result.json"))


def save_feedback(run_id: str, case_id: str, candidate_id: str | None, action: str, edited_text: str = "", operator: str | None = None, *, root: Path = PROJECT_ROOT) -> dict[str, Any]:
    if action not in {"select", "edit", "discard", "copy"}:
        raise ValueError("反馈动作须为 select、edit、discard 或 copy")
    result = load_result(run_id, case_id, root=root)
    if result.status != "success":
        raise ValueError("只有成功生成的原稿可以选稿或编辑")
    candidates = {item.candidate_id: item for item in result.candidates}
    if candidate_id not in candidates and not (candidate_id is None and action == "discard"):
        raise ValueError("候选不存在于指定运行和案例中")
    if action == "edit" and not edited_text.strip():
        raise ValueError("编辑稿不能为空")
    feedback = {"feedback_id": uuid.uuid4().hex, "created_at": timestamp(), "run_id": run_id, "case_id": case_id, "candidate_id": candidate_id, "action": action, "edited_text": edited_text.strip() if action in {"edit", "copy"} else "", "operator": operator, "sent": False}
    append_jsonl(case_directory(run_id, case_id, root=root) / "feedback.jsonl", feedback)
    return feedback
