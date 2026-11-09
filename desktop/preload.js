// 预加载：向页面暴露受控的桌面能力（截图 OCR、剪贴板、窗口行为）。
// 页面侧合同：window.qixu.captureAndOcr()、window.qixu.onOcrText(cb)、window.qixu.hide()、window.qixu.quit()
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("qixu", {
  captureAndOcr: () => ipcRenderer.invoke("floating:capture-ocr"),
  onOcrText: (callback) => {
    ipcRenderer.on("qixu:ocr-text", (_event, text) => callback(String(text || "")));
  },
  hide: () => ipcRenderer.send("floating:hide"),
  quit: () => ipcRenderer.send("floating:quit"),
});
