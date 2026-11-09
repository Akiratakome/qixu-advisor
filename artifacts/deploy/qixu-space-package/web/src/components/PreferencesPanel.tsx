import { useEffect, useState } from 'react'

import type { Customer, Preference } from '../api'
import { api, errorMessage } from '../api'

const KIND_LABELS: Record<string, string> = { like: '喜欢', dislike: '不喜欢', budget: '预算' }
const STATUS_LABELS: Record<string, string> = { pending: '待确认', confirmed: '已确认', revoked: '已撤销' }

interface PreferencesPanelProps {
  customers: Customer[]
  customerId: string | null
  onCustomerChange: (id: string | null) => void
}

export default function PreferencesPanel({ customers, customerId, onCustomerChange }: PreferencesPanelProps) {
  const [preferences, setPreferences] = useState<Preference[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [kind, setKind] = useState('like')
  const [originalText, setOriginalText] = useState('')
  const [explicit, setExplicit] = useState(true)
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    if (!customerId) {
      return
    }
    let cancelled = false
    void (async () => {
      try {
        const items = await api.preferences.list(customerId)
        if (!cancelled) {
          setPreferences(items)
          setLoadError(null)
        }
      } catch (error) {
        if (!cancelled) {
          setLoadError(errorMessage(error))
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [customerId])

  function handleCustomerChange(id: string | null) {
    setPreferences(null)
    setLoadError(null)
    setNotice(null)
    onCustomerChange(id)
  }

  async function refreshPreferences(target: string | null) {
    if (!target) {
      setPreferences(null)
      return
    }
    try {
      setPreferences(await api.preferences.list(target))
    } catch (error) {
      setLoadError(errorMessage(error))
    }
  }

  async function handlePatch(preferenceId: number, action: 'confirm' | 'revoke') {
    try {
      await api.preferences.patch(preferenceId, action)
      await refreshPreferences(customerId)
      setNotice(action === 'confirm' ? '已确认。' : '已撤销。')
    } catch (error) {
      setFormError(errorMessage(error))
    }
  }

  async function handleCreate() {
    if (!customerId) {
      setFormError('请先选择偏好所属客户。')
      return
    }
    if (!originalText.trim()) {
      setFormError('原文不能为空（须有来源）。')
      return
    }
    setSaving(true)
    setFormError(null)
    setNotice(null)
    try {
      await api.preferences.create(customerId, {
        kind,
        original_text: originalText.trim(),
        source: 'workbench',
        explicit,
      })
      setOriginalText('')
      await refreshPreferences(customerId)
      setNotice('偏好已保存；推测记录保持待确认。')
    } catch (error) {
      setFormError(errorMessage(error))
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="sidebar-section">
      <h3>偏好</h3>
      <label className="field">
        <span className="field-label">偏好所属客户</span>
        <select value={customerId ?? ''} onChange={(event) => handleCustomerChange(event.target.value || null)}>
          <option value="">未选择客户</option>
          {customers.map((customer) => (
            <option key={customer.customer_id} value={customer.customer_id}>
              {customer.customer_id}
            </option>
          ))}
        </select>
      </label>
      {loadError && <div className="alert error">{loadError}</div>}
      {preferences === null && customerId && !loadError && <p className="muted">偏好加载中…</p>}
      {preferences !== null && preferences.length === 0 && <p className="muted">该客户暂无偏好记录。</p>}
      {preferences !== null && preferences.length > 0 && (
        <table className="pref-table">
          <thead>
            <tr>
              <th>类别</th>
              <th>原文</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {preferences.map((preference) => (
              <tr key={preference.preference_id}>
                <td>{KIND_LABELS[preference.kind] ?? preference.kind}</td>
                <td className="pref-original">{preference.original_text}</td>
                <td>{STATUS_LABELS[preference.status] ?? preference.status}</td>
                <td className="pref-actions">
                  {preference.status !== 'confirmed' && (
                    <button
                      className="btn mini"
                      type="button"
                      onClick={() => void handlePatch(preference.preference_id, 'confirm')}
                    >
                      确认
                    </button>
                  )}
                  {preference.status !== 'revoked' && (
                    <button
                      className="btn mini danger"
                      type="button"
                      onClick={() => void handlePatch(preference.preference_id, 'revoke')}
                    >
                      撤销
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="pref-form">
        <h4>新增偏好</h4>
        <label className="field">
          <span className="field-label">类别</span>
          <select value={kind} onChange={(event) => setKind(event.target.value)}>
            <option value="like">喜欢</option>
            <option value="dislike">不喜欢</option>
            <option value="budget">预算</option>
          </select>
        </label>
        <label className="field">
          <span className="field-label">原文</span>
          <input
            type="text"
            value={originalText}
            onChange={(event) => setOriginalText(event.target.value)}
            placeholder="有来源的客户原话"
          />
        </label>
        <div className="field-inline">
          <label className="radio-option">
            <input type="radio" name="pref-explicit" checked={explicit} onChange={() => setExplicit(true)} />
            明确
          </label>
          <label className="radio-option">
            <input type="radio" name="pref-explicit" checked={!explicit} onChange={() => setExplicit(false)} />
            推测
          </label>
        </div>
        <button className="btn primary" type="button" disabled={saving} onClick={() => void handleCreate()}>
          {saving ? '保存中…' : '保存偏好'}
        </button>
        {notice && <p className="notice">{notice}</p>}
        {formError && <div className="alert error">{formError}</div>}
      </div>
    </section>
  )
}
