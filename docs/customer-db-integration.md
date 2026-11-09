# 外部客户数据库接入（示例：Supabase）

公司已有客户资料库时，可把「客户档案」数据源接进来。当前实现**只读**：外部库仅用于拉取客户档案（购买者/收礼人/偏好/历史）；**首次使用时缓存一份本地只读快照**（满足本地库外键约束），不回写外部库、不同步。

## 1. 表结构示例（Supabase SQL）

```sql
create table customers (
  id bigint generated always as identity primary key,
  client_id text unique not null,          -- 业务客户 ID（如 C001）
  display_name text,
  contact_permission text default 'allowed', -- allowed / denied
  profile jsonb not null default '{}'        -- {long_term_preferences, history, relationship}
);
```

`long_term_preferences`：`{"likes":["柑橘"],"dislikes":["甜香"]}`；
`history`：`[{"type":"purchase","sku_id":"QINGLAN-50","date":"2026-10-30"}]`。

## 2. 服务端环境变量

```bash
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_SERVICE_KEY=eyJ...      # service_role 密钥，仅服务端
```

## 3. 调用与回退

- 实现见 `src/qixu_advisor/sources.py`（`fetch_external_customer(profile_id)`）；
- 接入点：API 生成路径——会话选了客户、本地库没有该档案时，尝试外部源；命中则把档案合入本次生成请求的 `client_information`（本次会话用，不持久化）；
- 外部库未配置或未命中：回退本地 SQLite / 内置虚构目录；查不到仍按冷启动默认 prompt 生成。

## 4. 换一家数据库

`sources.py` 的 `fetch_external_customer` 是唯一扩展点：接 MySQL/Postgres/自建 CRM API 都只需新增一个读取函数（返回规范化档案 dict，字段见 `CANONICAL_KEYS`），不改生成核心。示例二（自建 API）：

```python
def fetch_crm_api_customer(profile_id):
    resp = httpx.get(f"{CRM_BASE}/customers/{profile_id}", headers={"Authorization": f"Bearer {CRM_TOKEN}"})
    resp.raise_for_status()
    return sources.canonicalize(resp.json())
```

## 5. 边界

- 外部数据仍是「待处理数据」：生成前的事实纪律与去 AI 味门禁不变；
- 不把外部资料写入提示之外的地方；不做双向同步（如需双向，作为独立功能另评估）。

## 6. 自定义数据源（非 Supabase）

接入其他客户库时，`src/qixu_advisor/sources.py` 的 **`fetch_external_customer(profile_id)` 是唯一扩展点**：
只要返回一个**规范化档案 dict**（字段见 `CANONICAL_KEYS`：`client_id`/`display_name`/
`contact_permission`/`long_term_preferences`/`history`/`relationship`，其余字段忽略），
生成核心与 API 均无需改动；未配置或未命中返回 `None` 即走本地回退。

工作台配置入口 **`GET/PUT /api/v1/settings/datasource`** 的 `supabase_url` 字段继续作为通用
**「外部数据源地址」**使用：兼容任意提供 `GET /customers?client_id=<id>` 查询的 HTTP 服务，
Supabase 只是默认示例；`supabase_service_key` 作对应服务密钥（如自建服务无鉴权可留空）。

最小自建 HTTP API 示例（FastAPI 骨架，返回规范化档案）：

```python
# 外部客户服务：GET /customers?client_id=C001 → 规范化档案（或 200 + null 表示未命中）
@app.get("/customers")
def get_customer(client_id: str):
    row = db.get(client_id)          # 自己的客户库查询
    if row is None:
        return None                  # 未命中：本地回退
    return {
        "client_id": row.client_id,
        "display_name": row.display_name,
        "contact_permission": row.contact_permission,
        "long_term_preferences": row.preferences,
        "history": row.history,
        "relationship": row.relationship,
    }
```

curl 验证（先在工作台「设置」里把该地址与密钥填入数据源配置）：

```bash
curl "http://127.0.0.1:8000/customers?client_id=C001"
# → {"client_id":"C001","display_name":"林女士","contact_permission":"allowed",...}
```

在 `sources.py` 中接入该服务（唯一扩展点示例，不改其他文件）：

```python
def fetch_external_customer(profile_id, *, timeout=10.0):
    url = os.environ.get("CUSTOMER_API_URL")            # 或读 runtime_settings 的 supabase_url
    if not url:
        return None
    resp = httpx.get(f"{url.rstrip('/')}/customers", params={"client_id": profile_id}, timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()
    return canonicalize(payload) if payload else None
```
