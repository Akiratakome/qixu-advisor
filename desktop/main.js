// 栖序 QIXU 悬浮顾问窗（Windows）
// 常驻置顶无边框小窗，加载工作台的 ?floating=1 极简卡片模式。
// 快捷键：Ctrl+Shift+Q 显示/隐藏；窗口内「隐藏」由页面消息驱动。
// 本壳只做窗口行为：截图/OCR/生成/复制全部由页面与后端完成。
const { app, BrowserWindow, globalShortcut, ipcMain, clipboard, screen } = require("electron");
const path = require("path");

const APP_URL = process.env.QIXU_APP_URL || "https://qixu-advisor.onrender.com/?floating=1";
let win = null;

function createWindow() {
  const { workArea } = screen.getPrimaryDisplay();
  win = new BrowserWindow({
    width: 420,
    height: 640,
    x: workArea.x + workArea.width - 440,
    y: workArea.y + 24,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    resizable: true,
    skipTaskbar: false,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  win.loadURL(APP_URL);
  win.on("closed", () => { win = null; });
}

function toggleWindow() {
  if (!win) { createWindow(); return; }
  if (win.isVisible()) { win.hide(); } else { win.show(); win.focus(); }
}

app.whenReady().then(() => {
  createWindow();
  globalShortcut.register("Ctrl+Shift+Q", toggleWindow);
  ipcMain.handle("floating:paste", () => clipboard.readText());
  ipcMain.handle("floating:copy", (_event, text) => { clipboard.writeText(String(text)); return true; });
  ipcMain.on("floating:hide", () => { if (win) win.hide(); });
});

app.on("window-all-closed", () => { app.quit(); });
app.on("will-quit", () => { globalShortcut.unregisterAll(); });
