# 栖序 QIXU 悬浮顾问窗（桌面伴生应用 MVP）

按用户要求的「悬浮框小应用」：常驻置顶小窗 → 粘贴客户消息（或先截图后 OCR，见下）→ 生成三条可编辑卡片 → 点一下可改 → 确认复制 → 窗口隐藏。页面能装下更多消息记录，不用来回切窗口。

## 运行

```powershell
cd desktop
npm install          # 安装 Electron（首次）
npm start            # 打开悬浮窗，加载 QIXU_APP_URL 或默认线上工作台 ?floating=1
```

- `Ctrl+Shift+Q`：显示/隐藏悬浮窗；
- 窗口内粘贴消息 → 生成 → 卡片就地修改 → 【复制】（写入剪贴板）→ 【隐藏】收起；
- 自定义后端：`$env:QIXU_APP_URL="http://127.0.0.1:8000/?floating=1"`。

## 截图/OCR（下一步，MVP 未内置）

读屏截取最新客户消息需要操作系统截图 + OCR：计划用 PowerShell 截取选区（`System.Drawing.CopyFromScreen`）＋ Windows.Media.Ocr 识别中文，把文本喂给本应用输入框。当前 MVP 先用「粘贴」通道（微信 PC 端选中复制即可），功能等价、零隐私面（不碰屏幕与剪贴板以外内容）。

## 边界

- 应用不自动发送微信；复制、保存仅本地记录；
- 所有资料虚构；生成走同一 API 与去 AI 味门禁。
