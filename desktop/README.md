# 栖序 QIXU 悬浮顾问窗（桌面伴生应用，x64）

常驻置顶小窗：**截图识别微信聊天 → 三条可编辑卡片 → 复制 → 隐藏**。页面能装下更多消息记录，不用来回切窗口。

## 快捷键与按钮

| 操作 | 效果 |
|---|---|
| `Ctrl+Shift+Q` | 显示/隐藏悬浮窗 |
| `Ctrl+Shift+A` | **截图并 OCR**（截取当前主屏 → 系统 OCR 识别聊天文字 → 自动填入输入框，确认后生成） |
| 窗口内【截图识别】 | 同上（按钮触发） |
| 窗口内【隐藏】 | 收起窗口（后台常驻） |
| 窗口内【关闭】 | 退出应用 |
| 卡片【复制】 | 复制当前编辑值到剪贴板（留证） |
| 卡片【👍 更好 / 👎 不好】 | 比较反馈，供后续训练迭代 |

## 运行（开发）

```powershell
cd desktop
npm install        # 或 npm ci（国内网络可用 npmmirror 镜像）
npm start          # 加载 QIXU_APP_URL 或默认线上工作台 ?floating=1
```

自定义后端：`$env:QIXU_APP_URL="http://127.0.0.1:8000/?floating=1"`。

## OCR 说明

- Windows：系统自带 Windows.Media.Ocr（中文可靠，无需额外安装）；识别的是**当前主屏**内容——请先把微信窗口放在前台；
- macOS / Linux：当前版本提示「仅 Windows 支持截图识别」，可直接复制聊天文字粘贴；OCR 扩展点保留在 `main.js` 的 `runOcr()`。

## 打包与下载（win / mac / linux，x64）

- 本地打包：`npm run dist:win`（Windows）｜`npm run dist:linux`（Linux AppImage）｜`npm run dist:mac`（仅 macOS 上可打 dmg）；
- **GitHub Releases**：仓库内置 `.github/workflows/release-desktop.yml`——推送 `desktop-v*` 标签即在 GitHub Actions 上自动构建三个平台 x64 安装包并发布为 Release 附件（下载页：仓库 → Releases）。mac 包必须由 mac runner 构建（工作流已含）。

## 数据源扩展性

悬浮窗走同一后端 API；外部客户库通过 `docs/customer-db-integration.md` 的扩展点接入（Supabase 只是默认示例，自建 HTTP API 同样支持）。

## 边界

- 应用不自动发送微信；复制、保存仅本地记录；全部资料虚构。
