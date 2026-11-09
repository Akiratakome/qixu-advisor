import { useState } from 'react'

import type { Draft } from '../api'
import { api, errorMessage } from '../api'

type CopyState = 'idle' | 'copied' | 'failed' | 'recording-failed'

interface DraftCardProps {
  draft: Draft
  index: number
  onDraftUpdated: (updated: Draft) => void
  onNotice: (message: string) => void
  onDirtyChange: (draftId: number, dirty: boolean) => void
  // 悬浮卡片模式：只保留正文编辑与复制，复制成功后整卡高亮「已复制」。
  minimal?: boolean
}

export default function DraftCard({ draft, index, onDraftUpdated, onNotice, onDirtyChange, minimal = false }: DraftCardProps) {
  const [text, setText] = useState(draft.text)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [copyState, setCopyState] = useState<CopyState>('idle')
  const [acting, setActing] = useState(false)

  const dirty = text !== draft.text

  function handleTextChange(value: string) {
    setText(value)
    onDirtyChange(draft.draft_id, value !== draft.text)
  }

  async function handleCopy() {
    // 复制始终读取点击当下的编辑值（含未保存修改）；成功后才提示，不先等后端保存。
    try {
      await navigator.clipboard.writeText(text)
      setCopyState('copied')
    } catch {
      setCopyState('failed')
    }
    try {
      await api.drafts.action(draft.draft_id, {
        action: 'copied',
        copied_text: text,
        base_revision: draft.revision,
      })
    } catch {
      setCopyState('recording-failed')
    }
  }

  async function handleSave() {
    if (!text.trim()) {
      setSaveError('修改不能为空。')
      return
    }
    setSaving(true)
    setSaveError(null)
    try {
      const updated = await api.drafts.patch(draft.draft_id, {
        text: text.trim(),
        expected_revision: draft.revision,
      })
      onDraftUpdated(updated)
      onDirtyChange(draft.draft_id, false)
      onNotice('修改已保存。')
    } catch (error) {
      setSaveError(errorMessage(error))
    } finally {
      setSaving(false)
    }
  }

  async function handleAction(action: 'selected' | 'discarded') {
    setActing(true)
    try {
      await api.drafts.action(draft.draft_id, { action, base_revision: draft.revision })
      onNotice(action === 'selected' ? '已选用。' : '已弃用。')
    } catch (error) {
      onNotice(`处理失败：${errorMessage(error)}`)
    } finally {
      setActing(false)
    }
  }

  const copiedClass = minimal && copyState === 'copied' ? 'copied-card' : ''

  return (
    <article className={`draft-card ${copiedClass}`}>
      <div className="draft-card-head">
        <span className="draft-no">候选 {index}</span>
        {minimal && copyState === 'copied' && <span className="copied-badge">已复制</span>}
        {dirty && <span className="draft-meta">有未保存修改</span>}
      </div>
      <textarea
        className="draft-editor"
        value={text}
        onChange={(event) => handleTextChange(event.target.value)}
        rows={3}
      />
      {copyState === 'failed' && <p className="form-error">自动复制失败，请手动选中正文复制。</p>}
      {copyState === 'recording-failed' && <p className="form-error">复制成功，但保存记录失败，请重试。</p>}
      {saveError && <p className="form-error">{saveError}</p>}
      <div className="draft-actions">
        <button className="btn copy" type="button" onClick={() => void handleCopy()}>
          复制{copyState === 'copied' ? ' ✓' : ''}
        </button>
        {!minimal && (
          <>
            <button className="btn primary" type="button" disabled={saving || !dirty} onClick={() => void handleSave()}>
              {saving ? '保存中…' : '保存修改'}
            </button>
            <button className="btn ghost" type="button" disabled={acting} onClick={() => void handleAction('selected')}>
              选用
            </button>
            <button className="btn ghost danger" type="button" disabled={acting} onClick={() => void handleAction('discarded')}>
              弃用
            </button>
          </>
        )}
      </div>
    </article>
  )
}
