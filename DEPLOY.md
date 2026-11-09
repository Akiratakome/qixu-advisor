# 公开部署说明（供用户/运维执行）

目标：给招聘团队的链接无需账号即可打开。当前产品形态 = **单进程 FastAPI + React 静态 + SQLite**（React 工作台为默认界面），推荐 Docker 平台。

## 方式一：Hugging Face Spaces（Docker，推荐）

前置：一个 Hugging Face 账号。无需 GitHub。

1. 打开 https://huggingface.co/new-space → Owner 选自己 → Space SDK 选 **Docker** → 可见性选 Public。
2. 本仓库 `Dockerfile` 已就绪（Node 构建前端 → Python 运行，`PORT` 环境变量兼容 HF）；把 `src/`、`data/`、`scripts/`、`web/`、`Dockerfile`、`pyproject.toml` 按仓库结构推送到 Space（用 Git：`git remote add space https://huggingface.co/spaces/<你>/<space名>`，push 后自动构建）。
3. 密钥：Space → Settings → Variables and secrets → New secret，名 `DEEPSEEK_API_KEY`，值填密钥（容器内读取环境变量）。
4. 构建完成后公开 URL 免账号可开。`README-HF.md` 的内容可复制为 Space 首页说明。

注意：Space 免费额度下持久盘有限；如需长期保存运行库，建议换 Render（带持久盘）。公开实例会真实调用模型（按量计费），演示成本自控。

## 方式二：Render（Docker + 持久盘，推荐长期）

前置：Render 账号（GitHub 或邮箱登录）。

1. 把仓库推送到 GitHub（公开或私有均可）。
2. render.com → New → Blueprint → 选择仓库；`render.yaml` 已配好（Docker 运行时、健康检查 `/api/v1/settings/model`、1GB 持久盘挂 /app/runtime）。
3. Dashboard 里给服务填环境变量 `DEEPSEEK_API_KEY`。
4. 部署完成后获得 `https://<name>.onrender.com` 公开链接。

## 方式三：自有服务器（单实例）

任意带持久盘的 Linux 主机：`docker build -t qixu .` → `docker run -d -p 8000:8000 -v qixu-runtime:/app/runtime -e DEEPSEEK_API_KEY=... qixu` → 反向代理加 HTTPS（Caddy/Nginx）。

## 方式四：Streamlit 管理/评价入口（可选，单独部署）

Streamlit Community Cloud：Main file path 填 `src/qixu_advisor/app.py`（管理/人工评价入口，React 工作台不需要它）。

## 演示注意事项

- 演示走「粘贴对话 → 自动理解需求 → 生成三条 → 就地修改复制」流程，可现场输入新对话（不依赖固定 50 例）。
- 应用侧栏可自配模型 API（密钥仅存本实例运行库）；不发送微信、不自动发布。
- 全部资料虚构，无真实客户隐私。

## 交接后：密钥安全与「他们自己的模型」

**密钥安全（上交后）**
1. 应用支持**运行时自配模型**：界面侧栏「模型配置」可填 base_url/model/api_key（存本实例运行库，永不回显）。招聘团队想用自己的账号时，直接在界面里换——不需要重新部署。
2. 服务端环境变量 `DEEPSEEK_API_KEY` 是部署时注入的；如不希望评审消耗你的余额，**收尾后可在平台控制台删除该变量**（应用会提示「尚未配置密钥」，评审者按第 1 条自配即可）。
3. 安全建议：提交前轮换你用过/发过的密钥（Render API key、DeepSeek key）；服务端密钥从不进仓库与交付包（已核实）。

**如何确认他们自己的模型能工作（自测端点）**
- 界面「模型配置」保存后，应用生成/分析立即使用新配置；
- 提供 `POST /api/v1/settings/model/test`：用当前配置访问 `{base_url}/models` 做连通性自测，返回 `{"ok":true,"models":[...]}` 或友好失败原因（凭据无效/余额不足/无法连接）——不回显密钥。评审者可先在界面保存自己的配置，再点「测试连接」确认，然后直接生成。
- 模型兼容条件：任何兼容 OpenAI Chat Completions 的接口（`/chat/completions`，支持 JSON 输出与 temperature/top_p）即可；不支持的参数（如某些厂商不认 top_p）在界面把 top_p 留空即可回退默认。

## 悬浮框小应用（可行性）

- 目标（读屏/截图 → 最新客户消息 → 三张可编辑卡片 → 复制后窗口消失）需要**桌面端能力**：浏览器网页无法读屏幕或截取其他窗口。
- 可行方案：桌面伴生小应用（Tauri/Electron + WebView2，复用现有 React 卡片组件）：全局快捷键截取选区 → Windows OCR 提取文字 → 调现有 API 生成 → 常驻置顶小窗展示三张卡片（点击改、确认复制、Esc 关闭）。
- 当前定位：交付后作为可选演示增强（PDF 不要求）；核心 API 已就绪，无需改后端。
