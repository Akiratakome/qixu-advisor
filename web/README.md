# 栖序 QIXU · 顾问工作台（Web）

React + TypeScript + Vite 的顾问写作前端；FastAPI 提供 `/api/v1` 接口，Vite 开发服务器把 `/api` 代理到 `http://127.0.0.1:8000`。品牌、客户与业务资料均为虚构。

## 开发

```bash
npm install        # 或 npm ci（使用 package-lock.json）
npm run dev        # http://localhost:5173，/api 代理到 127.0.0.1:8000
```

后端启动（由服务端负责）：

```bash
uvicorn qixu_advisor.api:app --host 127.0.0.1 --port 8000
```

## 构建与检查

```bash
npm run build      # tsc -b && vite build；产物在 dist/（不入库）
npm run lint       # oxlint
```

生产部署时由反向代理把静态页面与 `/api` 同源托管；`vite preview` 不作为生产服务。

## 目录

| 路径 | 职责 |
| --- | --- |
| `src/api.ts` | 与 `api_models.py` 对齐的 typed fetch 客户端，统一解析 `{error:{code,message,fields?}}` |
| `src/chat.ts` | 对话行解析（客户：/顾问：前缀）与六场景常量 |
| `src/App.tsx` | 页面编排：会话切换、消息流、分析、生成、草稿卡 |
| `src/components/` | Sidebar（会话/写作设置/偏好/模型状态）、PreferencesPanel、MessageStream、Composer、AnalysisPanel、DraftCard |

约束：重绘不调用模型（仅「分析并提问」「生成三条候选」触发）；保存与复制不等于发送；草稿编辑/选用/弃用/复制均经 API 留证；界面不展示 run_id 或原始 JSON。
