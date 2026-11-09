"""S3 生产形态入口：FastAPI + React 静态前端。

用法（项目根）：
  ./.venv/Scripts/python.exe -m uvicorn scripts.serve_api:app --host 127.0.0.1 --port 8000
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qixu_advisor.api import create_app  # noqa: E402

_db = ROOT / "runtime" / "qixu.sqlite3"
_dist = ROOT / "web" / "dist" if (ROOT / "web" / "dist" / "index.html").exists() else None
app = create_app(_db, root=ROOT, static_dir=_dist)
