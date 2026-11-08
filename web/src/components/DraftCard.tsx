import { useState } from 'react'

import type { Draft } from '../api'
import { api, errorMessage } from '../api'

type CopyState = 'idle' | 'copied' | 'failed' | 'recording-failed'

interface DraftCardProps {
  draft: Draft
  index: number
  onDraftUpdated: (updated: Draft) => void
  onNotice: (message: string) => void
}

export default function DraftCard({ draft, index, onDraftUpdated, onNotice }: DraftCardProps) {
  const [editText, setEditText] = useState(draft.text)
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [editError, setEditError] = useState<string | null>(null)
  const [copyState, setCopyState] = useState<CopyState>('idle')
  const [acting, setActing] = useState(false)

  const currentText = editText !== draft.text ? editText : draft.text

  async function handleCopy() {
    // 复制读取点击当下的正文（含未保存修改）；成功后才提示，不先等后端保存。
    try {
      await navigator.clipboard.writeText(currentText)
      setCopyState('copied')
    } catch {
      setCopyState('failed')
    }
    try {
      await api.drafts.action(draft.draft_id, {
        action: 'copied',
        copied_text: currentText,
        base_revision: draft.revision,
      })
    } catch {
      setCopyState('recording-failed')
    }
  }

  async function handleSaveEdit() {
    if (!editText.trim()) {
      setEditError('编辑稿不能为空。')
      return
    }
    setSaving(true)
    setEditError(null)
    try {
      const updated = await api.drafts.patch(draft.draft_id, {
        text: editText.trim(),
        expected_revision: draft.revision,
      })
      onDraftUpdated(updated)
      setEditing(false)
      onNotice('编辑稿已保存；机器原稿保留在证据链中。')
    } catch (error) {
      setEditError(errorMessage(error))
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
          一条完整微信消息{editing ? ' · 有未保存修改' : ''} · 保存与复制均不会发送
        </span>
      </div>
      <div className="draft-body">{currentText}</div>
      {copyState === 'failed' && <div className="alert error">自动复制失败，请手动选中正文复制。</div>}
      {copyState === 'recording-failed' && <div className="alert error">复制成功，但留证失败，请重试。</div>}
      <div className="draft-actions">
        <button className="btn copy" type="button" onClick={handleCopy}>
          复制{copyState === 'copied' ? ' · 已复制' : ''}
        </button>
        <button className="btn ghost" type="button" onClick={() => setEditing((value) => !value)}>
          {editing ? '收起编辑' : '编辑'}
        </button>
        <button className="btn ghost" type="button" disabled={acting} onClick={() => handleAction('selected')}>
          选用
        </button>
        <button className="btn ghost danger" type="button" disabled={acting} onClick={() => handleAction('discarded')}>
          弃用
        </button>
      </div>
      {editing && (
        <div className="draft-edit">
          <textarea
            className="draft-editor"
            value={editText}
            onChange={(event) => setEditText(event.target.value)}
            rows={5}
          />
          <div className="draft-edit-footer">
            <button className="btn primary" type="button" disabled={saving} onClick={handleSaveEdit}>
              {saving ? '保存中…' : '编辑并保存'}
            </button>
            <span className="muted">保存后追加一条修订；机器原稿保持不变。</span>
          </div>
          {editError && <div className="alert error">{editError}</div>}
        </div>
      )}
    </article>
  )
}
