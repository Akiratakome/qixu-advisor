// 栖序 QIXU 悬浮顾问窗（Windows / macOS / Linux，x64）
// 常驻置顶无边框小窗，加载工作台的 ?floating=1 极简卡片模式。
// 快捷键：Ctrl+Shift+Q 显示/隐藏；Ctrl+Shift+A 截图并 OCR（Windows 用系统 OCR，其余平台提示不支持）。
// 截图/OCR 结果通过 preload 暴露给页面（window.qixu），生成/复制由页面与后端完成。
const { app, BrowserWindow, globalShortcut, ipcMain, clipboard, screen, desktopCapturer } = require("electron");
const { execFile } = require("child_process");
const fs = require("fs");
const os = require("os");
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
      preload: path.join(__dirname, "preload.js"),
    },
  });
  win.loadURL(APP_URL);
  win.on("closed", () => { win = null; });
}

function toggleWindow() {
  if (!win) { createWindow(); return; }
  if (win.isVisible()) { win.hide(); } else { win.show(); win.focus(); }
}

function sendOcr(text) {
  if (win) win.webContents.send("qixu:ocr-text", text);
}

// Windows OCR 会在中文字符间插入空格，清理后便于粘贴生成。
function cleanupOcr(text) {
  return String(text || "")
    .replace(/([\u4e00-\u9fff])\s+([\u4e00-\u9fff])/g, "$1$2")
    .replace(/．/g, "，")
    .trim();
}

// 截取主屏 → 存临时 PNG；返回文件路径。mac 需在系统设置授予「屏幕录制」权限。
async function captureScreen() {
  const sources = await desktopCapturer.getSources({ types: ["screen"], thumbnailSize: screen.getPrimaryDisplay().size });
  if (!sources.length) throw new Error("没有可用的屏幕源");
  const image = sources[0].thumbnail.toPNG();
  const file = path.join(os.tmpdir(), `qixu-shot-${Date.now()}.png`);
  fs.writeFileSync(file, image);
  return file;
}

// Windows：系统自带 Windows.Media.Ocr（中文识别可靠，无需额外安装）。
// 其他平台：返回提示，接入 tesseract 等 OCR 后可扩展（保留扩展点）。
function runOcr(imagePath) {
  return new Promise((resolve, reject) => {
    const script = path.join(__dirname, "ocr-windows.ps1");
    execFile(
      "powershell.exe",
      ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script, "-ImagePath", imagePath],
      { encoding: "utf8", timeout: 30000, windowsHide: true },
      (error, stdout) => {
        if (error) { reject(new Error("OCR 失败：" + (stdout || error.message).trim())); return; }
        resolve(String(stdout).trim());
      },
    );
  });
}

async function captureAndOcr() {
  if (process.platform !== "win32") {
    sendOcr("当前版本仅 Windows 支持截图识别；请直接复制聊天文字粘贴进来。");
    return;
  }
  try {
    const file = await captureScreen();
    const text = await runOcr(file);
    fs.rm(file, { force: true }, () => {});
    if (!text) { sendOcr("没有识别到文字，请让微信窗口置前后再试。"); return; }
    sendOcr(cleanupOcr(text));
  } catch (err) {
    sendOcr(String(err && err.message ? err.message : err));
  }
}

app.whenReady().then(() => {
  createWindow();
  globalShortcut.register("Ctrl+Shift+Q", toggleWindow);
  globalShortcut.register("Ctrl+Shift+A", captureAndOcr);
  ipcMain.handle("floating:paste", () => clipboard.readText());
  ipcMain.handle("floating:copy", (_event, text) => { clipboard.writeText(String(text)); return true; });
  ipcMain.handle("floating:capture-ocr", captureAndOcr);
  ipcMain.on("floating:hide", () => { if (win) win.hide(); });
  ipcMain.on("floating:quit", () => app.quit());
});

app.on("window-all-closed", () => { app.quit(); });
app.on("will-quit", () => { globalShortcut.unregisterAll(); });
