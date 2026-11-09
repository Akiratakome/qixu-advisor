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
