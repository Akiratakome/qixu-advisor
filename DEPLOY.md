# 公开部署说明（供用户/运维执行）

目标：给招聘团队的链接无需账号即可打开。推荐 Streamlit Community Cloud（免费、观众无需登录）。

## 方式一：Streamlit Community Cloud（推荐）

前置：一个 GitHub 账号（存放代码仓库）；本仓库代码已就绪（`requirements.txt` 为 `-e .`，`.streamlit/config.toml` 含主题与最小工具栏）。

1. 把本仓库推送到你的 GitHub 公开仓库（`.env` 与密钥不要提交；`.gitignore` 已排除）。
2. 打开 https://share.streamlit.io ，用 GitHub 登录，New app → 选仓库 → Main file path 填 `src/qixu_advisor/app.py` → Deploy。
3. Secrets 配置（Settings → Secrets）：
   ```toml
   DEEPSEEK_API_KEY = "你的密钥"
   ```
4. 部署完成后访问应用 URL：公开、免账号。
5. 每次代码更新后仓库 push，Community Cloud 自动重新部署。

注意：公开实例会真实调用 DeepSeek（按量计费）；如需限制演示成本，可临时换用低用量或由招聘团队按约定演示。业务资料全部虚构，不涉及真实客户隐私。

## 方式二：自有服务器（单实例）

任意带持久盘的 Linux 主机：安装 Python 3.12 → `pip install -e .` → 配置 `.env` → `streamlit run src/qixu_advisor/app.py --server.address 0.0.0.0 --server.port 8501` → 反向代理加 HTTPS（如 Caddy/Nginx）。数据目录（artifacts/runs、artifacts/evaluations）放在持久盘并定期备份。

## 演示注意事项

- 演示走「对话 → 分析并提问 → 确认 → 生成」流程，可现场输入新对话（不依赖固定 50 例）。
- 侧栏「人工评价」与「开发案例」为内部功能；正式演示可说明但不必展开。
- 应用不发送微信、不自动发布；保存与复制仅落本地记录。
