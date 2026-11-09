"""外部客户数据库接入示例（Supabase 风格）。

设计：公司的客户资料库与本地 SQLite 解耦。优先本地库，未命中时若配置了外部源，
按 profile_id 拉取并把资料合入本次生成请求（不落盘、不回写）。

外部源只读使用：POSTGREST/Supabase REST 端点 + 服务密钥（仅存服务端环境变量）。
示例表结构见 docs/customer-db-integration.md；本模块可被 api/conversations 调用。
"""

from __future__ import annotations

import os
from typing import Any

import httpx

CANONICAL_KEYS = (
    "client_id", "display_name", "contact_permission",
    "long_term_preferences", "history", "relationship",
)


def canonicalize(row: dict[str, Any]) -> dict[str, Any]:
    """把外部行映射为本项目客户档案；只取已知字段，其余忽略。"""
    profile = {key: value for key, value in row.items() if key in CANONICAL_KEYS and value is not None}
    if not profile.get("client_id") and row.get("id"):
        profile["client_id"] = row["id"]
    return profile


def supabase_configured() -> bool:
    return bool(os.environ.get("SUPABASE_URL")) and bool(os.environ.get("SUPABASE_SERVICE_KEY"))


def fetch_supabase_customer(profile_id: str, *, timeout: float = 10.0) -> dict[str, Any] | None:
    """GET {SUPABASE_URL}/rest/v1/customers?client_id=eq.{id}&select=* → 规范化档案。

    示例表（Supabase）：
      create table customers (
        id bigint generated always as identity primary key,
        client_id text unique not null,
        display_name text,
        contact_permission text default 'allowed',
        profile jsonb not null default '{}'
      );
    行内 profile 存 {long_term_preferences, history, relationship}；本函数把顶层列与
    profile 合并后 canonicalize。未命中（200 + 空数组）返回 None；服务错误上抛。
    """
    base = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_SERVICE_KEY"]
    url = f"{base}/rest/v1/customers?client_id=eq.{profile_id}&select=*"
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        response = client.get(url, headers=headers)
    if response.status_code != 200:
        raise RuntimeError(f"外部客户库查询失败（HTTP {response.status_code}），已中止本次请求")
    rows = response.json()
    if not rows:
        return None
    merged = dict(rows[0])
    profile = merged.get("profile") or {}
    if isinstance(profile, dict):
        merged.update(profile)
    return canonicalize(merged)


def fetch_external_customer(profile_id: str, *, timeout: float = 10.0) -> dict[str, Any] | None:
    """统一入口：当前只实现 Supabase 示例；接入其他库在此扩展（HTTP/RPC/自建 API 均可）。"""
    if supabase_configured():
        return fetch_supabase_customer(profile_id, timeout=timeout)
    return None


def ping_supabase(base_url: str, service_key: str, *, timeout: float = 10.0) -> tuple[bool, str]:
    """数据源连通性自测：GET {base_url}/rest/v1/ 带 apikey 头；返回 (ok, 友好原因)。

    仅用于「测试连接」，不做任何数据读取或写入；不回显密钥。
    """
    url = base_url.rstrip("/") + "/rest/v1/"
    headers = {"apikey": service_key, "Authorization": f"Bearer {service_key}"}
    try:
        with httpx.Client(timeout=timeout, trust_env=False, follow_redirects=False) as client:
            response = client.get(url, headers=headers)
    except httpx.TimeoutException:
        return False, "连接超时"
    except httpx.TransportError:
        return False, "连接失败，请核对地址"
    if response.status_code == 401 or response.status_code == 403:
        return False, "凭据无效"
    if response.status_code in (200, 404, 405):
        return True, "连接成功"
    return False, f"服务返回 HTTP {response.status_code}"
