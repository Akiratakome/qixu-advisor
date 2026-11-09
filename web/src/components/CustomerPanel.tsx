import { useState } from 'react'

import type { Customer } from '../api'
import { api, errorMessage } from '../api'
import DataSourcePanel from './DataSourcePanel'
import PreferencesPanel from './PreferencesPanel'

function customerName(customer: Customer): string {
  const profile = customer.profile
  return ((profile.display_name as string | undefined) ??
    (profile.name as string | undefined) ??
    customer.customer_id)
}

interface CustomerPanelProps {
  customers: Customer[]
  onChanged: () => void
  prefCustomerId: string | null
  onPrefCustomerChange: (id: string | null) => void
}

export default function CustomerPanel({
  customers,
  onChanged,
  prefCustomerId,
  onPrefCustomerChange,
}: CustomerPanelProps) {
  const [name, setName] = useState('')
  const [address, setAddress] = useState('')
  const [permission, setPermission] = useState('')
  const [likes, setLikes] = useState('')
  const [historyNote, setHistoryNote] = useState('')
  const [saving, setSaving] = useState(false)
  const [seeding, setSeeding] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  async function handleCreate() {
    if (!name.trim()) {
      setFormError('姓名不能为空。')
      return
    }
    setSaving(true)
    setFormError(null)
    setNotice(null)
    try {
      await api.customers.create({
        display_name: name.trim(),
        buyer: address.trim() ? { address: address.trim() } : undefined,
        contact_permission: permission === '' ? undefined : (permission as 'allowed' | 'denied'),
        long_term_preferences: likes.trim() ? { likes: [likes.trim()] } : undefined,
        relationship: historyNote.trim() || undefined,
      })
      setName('')
      setAddress('')
      setPermission('')
      setLikes('')
      setHistoryNote('')
      setNotice('客户已新建。')
      onChanged()
    } catch (error) {
      setFormError(errorMessage(error))
    } finally {
      setSaving(false)
    }
  }

  async function handleSeed() {
    setSeeding(true)
    setFormError(null)
    setNotice(null)
    try {
      await api.customers.seed()
      setNotice('示例客户已导入（不覆盖已有客户）。')
      onChanged()
    } catch (error) {
      setFormError(errorMessage(error))
    } finally {
      setSeeding(false)
    }
  }

  return (
    <div className="customer-panel">
      <div className="customer-list">
        {customers.length === 0 ? (
          <p className="muted">暂无客户档案，可导入示例客户或新建。</p>
        ) : (
          <ul className="customer-rows">
            {customers.map((customer) => (
              <li key={customer.customer_id}>
                <span className="customer-name">{customerName(customer)}</span>
                <span className="muted">{customer.customer_id}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="sidebar-head customer-actions">
        <button className="btn mini" type="button" disabled={seeding} onClick={() => void handleSeed()}>
          {seeding ? '导入中…' : '导入示例客户'}
        </button>
      </div>
      <div className="pref-form">
        <h4>新建客户</h4>
        <label className="field">
          <span className="field-label">姓名</span>
          <input type="text" value={name} onChange={(event) => setName(event.target.value)} placeholder="如：林女士" />
        </label>
        <label className="field">
          <span className="field-label">称呼（可选）</span>
          <input type="text" value={address} onChange={(event) => setAddress(event.target.value)} placeholder="消息里的称呼" />
        </label>
        <label className="field">
          <span className="field-label">联系意愿（可选）</span>
          <select value={permission} onChange={(event) => setPermission(event.target.value)}>
            <option value="">未填</option>
            <option value="allowed">允许联系</option>
            <option value="denied">拒绝联系</option>
          </select>
        </label>
        <label className="field">
          <span className="field-label">长期喜好（可选）</span>
          <input type="text" value={likes} onChange={(event) => setLikes(event.target.value)} placeholder="如：柑橘、清爽木质" />
        </label>
        <label className="field">
          <span className="field-label">购买记录简述（可选）</span>
          <input type="text" value={historyNote} onChange={(event) => setHistoryNote(event.target.value)} placeholder="如：曾购青岚 50 mL" />
        </label>
        <button className="btn primary" type="button" disabled={saving} onClick={() => void handleCreate()}>
          {saving ? '保存中…' : '保存客户'}
        </button>
        {notice && <p className="notice">{notice}</p>}
        {formError && <div className="alert error">{formError}</div>}
      </div>
      <PreferencesPanel customers={customers} customerId={prefCustomerId} onCustomerChange={onPrefCustomerChange} />
      <DataSourcePanel />
    </div>
  )
}
