// 网页内截图识别：tesseract.js + jsdelivr CDN 的中文语言包（chi_sim）。
// 桌面壳或测试可注入 window.__qixuOcr.recognizeImage 替身，避免加载模型。

import { recognize as tesseractRecognize } from 'tesseract.js'

declare global {
  interface Window {
    __qixuOcr?: {
      recognizeImage?: (file: Blob) => Promise<string>
    }
  }
}

const CHI_SIM_LANG_PATH = 'https://cdn.jsdelivr.net/npm/@tesseract.js-data/chi_sim@1.0.0/4.0.0_best_int'

export async function recognizeImage(file: Blob): Promise<string> {
  if (window.__qixuOcr?.recognizeImage) {
    return window.__qixuOcr.recognizeImage(file)
  }
  const result = await tesseractRecognize(file, 'chi_sim', {
    langPath: CHI_SIM_LANG_PATH,
  })
  return cleanupOcrText(result.data.text ?? '')
}

// 中文 OCR 结果常带多余空格与英文标点，清理成可直接粘贴的对话文本。
export function cleanupOcrText(text: string): string {
  return String(text || '')
    .replace(/([\u4e00-\u9fff])\s+([\u4e00-\u9fff])/g, '$1$2')
    .replace(/[ .]/g, (match) => (match === ' ' ? ' ' : '，'))
    .replace(/ +/g, ' ')
    .trim()
}

export function getPasteImage(event: { clipboardData?: DataTransfer | null }): File | null {
  const items = event.clipboardData?.items
  if (!items) {
    return null
  }
  for (const item of items) {
    if (item.type.startsWith('image/')) {
      const file = item.getAsFile()
      if (file) {
        return file
      }
    }
  }
  return null
}

export const OCR_FAILED_COPY = '识别失败：请直接复制聊天文字粘贴'

export const OCR_HINT_COPY = '支持截图识别：按 Win+Shift+S 截取微信聊天后，在输入框 Ctrl+V 粘贴图片；桌面小应用可用 Ctrl+Shift+A 一键截图识别'
