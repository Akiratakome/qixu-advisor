import { useState } from 'react'

import { parseChatLines } from '../chat'

interface ComposerProps {
  value: string
  onChange: (value: string) => void
  onSubmit: () => void
  busy: boolean
  disabled: boolean
}

export default function Composer({ value, onChange, onSubmit, busy, disabled }: ComposerProps) {
  const [touched, setTouched] = useState(false)
  const lines = parseChatLines(value)
  const valid = lines.length > 0 && lines.every((line) => line.content.trim().length > 0)
  const invalidInput = touched && !valid
  return (
    <div className="composer">
      <div className="composer-row">
        <textarea
          className="composer-input"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onBlur={() => setTouched(true)}
          placeholder={'客户：这次想给妹妹挑一款。\n顾问：她平时喜欢哪一类气味？'}
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
      {invalidInput && <p className="form-error">存在空内容的消息行，请补全后再添加。</p>}
    </div>
  )
}
