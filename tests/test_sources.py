import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from qixu_advisor import sources


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/rest/v1/customers?"):
            if self.headers.get("apikey") != "svc-test" or self.headers.get("Authorization") != "Bearer svc-test":
                self.send_response(401)
                self.end_headers()
                return
            if "client_id=eq.MISSING" in self.path:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b"[]")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps([
                {"client_id": "C001", "display_name": "林女士", "contact_permission": "allowed",
                 "profile": {"long_term_preferences": {"likes": ["甜花香"], "dislikes": []}, "history": [{"type": "trial", "product_id": "MUGUANG"}]}}
            ]).encode("utf-8"))
            return
        self.send_response(500)
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture()
def fake_supabase():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_fetch_supabase_customer_hit(monkeypatch, fake_supabase):
    monkeypatch.setenv("SUPABASE_URL", fake_supabase)
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "svc-test")
    profile = sources.fetch_supabase_customer("C001")
    assert profile["client_id"] == "C001"
    assert profile["display_name"] == "林女士"
    assert profile["long_term_preferences"]["likes"] == ["甜花香"]
    assert profile["history"][0]["product_id"] == "MUGUANG"
    assert "id" not in profile  # 顶层 id 不在规范字段内被剔除


def test_fetch_supabase_customer_miss_returns_none(monkeypatch, fake_supabase):
    monkeypatch.setenv("SUPABASE_URL", fake_supabase)
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "svc-test")
    assert sources.fetch_supabase_customer("MISSING") is None


def test_fetch_supabase_customer_bad_key_raises(monkeypatch, fake_supabase):
    monkeypatch.setenv("SUPABASE_URL", fake_supabase)
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "svc-wrong")
    with pytest.raises(RuntimeError):
        sources.fetch_supabase_customer("C001")


def test_fetch_external_customer_unconfigured_returns_none(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    assert sources.fetch_external_customer("C001") is None
