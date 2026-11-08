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
      <textarea
        className="composer-input"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onBlur={() => setTouched(true)}
        placeholder={'客户：这次想给妹妹挑一款。\n顾问：她平时喜欢哪一类气味？\n客户：她喜欢清爽一点的味道。'}
        rows={4}
      />
      <div className="composer-footer">
        <span className="composer-hint">每行一条消息，以「客户：」或「顾问：」开头；保存与复制均不会发送微信。</span>
        <button
          className="btn primary"
          type="button"
          disabled={disabled || busy || lines.length === 0}
          onClick={onSubmit}
        >
          {busy ? '正在写入…' : '添加消息'}
        </button>
      </div>
      {invalidInput && <p className="form-error">存在空内容的消息行，请补全后再添加。</p>}
    </div>
  )
}
