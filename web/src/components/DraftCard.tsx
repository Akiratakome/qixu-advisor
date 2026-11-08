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
}

export default function DraftCard({ draft, index, onDraftUpdated, onNotice, onDirtyChange }: DraftCardProps) {
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
      onNotice('修改已保存；机器原稿保留在证据链中，基准修订已更新。')
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
      onNotice(action === 'selected' ? '已选用留证。' : '已弃用留证。')
    } catch (error) {
      onNotice(`处理失败：${errorMessage(error)}`)
    } finally {
      setActing(false)
    }
  }

  return (
    <article className="draft-card">
      <div className="draft-card-head">
        <span className="draft-no">候选 {index}</span>
        <span className="draft-meta">
          直接编辑正文 · 复制读取当下修改{dirty ? ' · 有未保存修改' : ''} · 保存与复制均不会发送
        </span>
      </div>
      <textarea
        className="draft-editor"
        value={text}
        onChange={(event) => handleTextChange(event.target.value)}
        rows={6}
      />
      {copyState === 'failed' && <div className="alert error">自动复制失败，请手动选中正文复制。</div>}
      {copyState === 'recording-failed' && <div className="alert error">复制成功，但留证失败，请重试。</div>}
      {saveError && <div className="alert error">{saveError}</div>}
      <div className="draft-actions">
        <button className="btn copy" type="button" onClick={() => void handleCopy()}>
          复制{copyState === 'copied' ? ' · 已复制' : ''}
        </button>
        <button className="btn primary" type="button" disabled={saving || !dirty} onClick={() => void handleSave()}>
          {saving ? '保存中…' : '保存修改'}
        </button>
        <button className="btn ghost" type="button" disabled={acting} onClick={() => void handleAction('selected')}>
          选用
        </button>
        <button className="btn ghost danger" type="button" disabled={acting} onClick={() => void handleAction('discarded')}>
          弃用
        </button>
      </div>
    </article>
  )
}
