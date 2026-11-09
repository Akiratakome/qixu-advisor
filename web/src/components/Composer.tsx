import { useState } from 'react'

import { parseChatLines } from '../chat'
import { OCR_FAILED_COPY, OCR_HINT_COPY, getPasteImage, recognizeImage } from '../ocr'

interface ComposerProps {
  value: string
  onChange: (value: string) => void
  onSubmit: () => void
  busy: boolean
  disabled: boolean
}

export default function Composer({ value, onChange, onSubmit, busy, disabled }: ComposerProps) {
  const [touched, setTouched] = useState(false)
  const [ocrBusy, setOcrBusy] = useState(false)
  const [ocrError, setOcrError] = useState<string | null>(null)
  const lines = parseChatLines(value)
  const valid = lines.length > 0 && lines.every((line) => line.content.trim().length > 0)
  const invalidInput = touched && !valid

  async function handlePaste(event: React.ClipboardEvent<HTMLTextAreaElement>) {
    const file = getPasteImage(event)
    if (!file) {
      return
    }
    // 剪贴板里有图片：走截图识别，纯文本粘贴行为不变。
    event.preventDefault()
    setOcrBusy(true)
    setOcrError(null)
    try {
      const text = (await recognizeImage(file)).trim()
      if (text) {
        onChange(`${value}${value ? '\n' : ''}${text}`)
      } else {
        setOcrError(OCR_FAILED_COPY)
      }
    } catch {
      setOcrError(OCR_FAILED_COPY)
    } finally {
      setOcrBusy(false)
    }
  }

  return (
    <div className="composer">
      <div className="composer-row">
        <textarea
          className="composer-input"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onBlur={() => setTouched(true)}
          onPaste={(event) => void handlePaste(event)}
          placeholder="添加聊天记录进行分析"
          rows={2}
        />
        <button
          className="btn primary composer-submit"
          type="button"
          disabled={disabled || busy || lines.length === 0}
          onClick={onSubmit}
        >
          {busy ? '写入中…' : '添加消息'}
        </button>
      </div>
      {ocrBusy && <p className="composer-subhint ocr-busy">识别中…</p>}
      <p className="composer-subhint">{OCR_HINT_COPY}</p>
      {ocrError && <p className="form-error">{ocrError}</p>}
      {invalidInput && <p className="form-error">存在空内容的消息行，请补全后再添加。</p>}
    </div>
  )
}
