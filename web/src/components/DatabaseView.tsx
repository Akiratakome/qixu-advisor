import { useEffect, useState } from 'react'

import type { Customer, DatasourceSettings } from '../api'
import { api, errorMessage } from '../api'

import DataSourcePanel from './DataSourcePanel'

const PERMISSION_LABELS: Record<string, string> = {
  allowed: '允许联系',
  denied: '拒绝联系',
}

function displayName(customer: Customer): string {
  const profile = customer.profile
  return ((profile.display_name as string | undefined) ??
    (profile.name as string | undefined) ??
    ((profile.buyer as { address?: string } | undefined)?.address) ??
    customer.customer_id)
}

function contactPermission(customer: Customer): string {
  const value = customer.profile.contact_permission
  if (typeof value === 'string') {
    return PERMISSION_LABELS[value] ?? '未填'
  }
  return '未填'
}

function longTermPreferences(customer: Customer): string {
  const value = customer.profile.long_term_preferences
  if (value && typeof value === 'object') {
    const preferences = value as { likes?: unknown; dislikes?: unknown; notes?: unknown }
    const parts: string[] = []
    if (Array.isArray(preferences.likes) && preferences.likes.length > 0) {
      parts.push(`喜欢：${preferences.likes.map(String).join('、')}`)
    }
    if (Array.isArray(preferences.dislikes) && preferences.dislikes.length > 0) {
      parts.push(`不喜欢：${preferences.dislikes.map(String).join('、')}`)
    }
    if (typeof preferences.notes === 'string' && preferences.notes) {
      parts.push(preferences.notes)
    }
    if (parts.length > 0) {
      return parts.join('；')
    }
  }
  return '—'
}

function purchaseSummary(customer: Customer): string {
  const relationship = customer.profile.relationship
  if (typeof relationship === 'string' && relationship) {
    return relationship
  }
  return '—'
}

// 本地客户档案总览（?view=database）：状态卡 + 客户表格；无侧栏，附「返回工作台」。
export default function DatabaseView() {
  const [customers, setCustomers] = useState<Customer[] | null>(null)
  const [datasource, setDatasource] = useState<DatasourceSettings | null>(null)
  const [seeding, setSeeding] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const list = await api.customers.list()
        if (!cancelled) {
          setCustomers(list)
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(errorMessage(loadError))
        }
      }
    })()
    void (async () => {
      try {
        const settings = await api.datasource.get()
        if (!cancelled) {
          setDatasource(settings)
        }
      } catch {
        if (!cancelled) {
          setDatasource({ supabase_url: null })
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  async function handleSeed() {
    setSeeding(true)
    setError(null)
    setNotice(null)
    try {
      await api.customers.seed()
      setNotice('示例客户已导入。')
      setCustomers(await api.customers.list())
    } catch (seedError) {
      setError(errorMessage(seedError))
    } finally {
      setSeeding(false)
    }
  }

  return (
    <div className="database-view">
      <header className="top-bar">
        <span className="bar-brand">
          栖序 QIXU<span className="bar-sub"> · 资料均为虚构</span>
        </span>
        <span className="db-title">本地客户档案</span>
        <span className="spacer" />
        <a className="btn mini" href="/">
          ← 返回工作台
        </a>
      </header>
      <div className="db-status-row">
        <span className="status-chip">数据源：本地库已连接</span>
        {datasource?.supabase_url ? (
          <span className="status-chip" title={datasource.supabase_url}>
            外部库已配置 · {datasource.supabase_url}
            <span className={`key-badge ${datasource.service_key_set ? 'set' : ''}`}>
              {datasource.service_key_set ? '密钥已设置' : '未设置密钥'}
            </span>
          </span>
        ) : (
          <span className="status-chip muted-chip">未配置外部库（使用本地客户档案）</span>
        )}
        <button className="btn mini primary" type="button" disabled={seeding} onClick={() => void handleSeed()}>
          {seeding ? '导入中…' : '导入示例客户'}
        </button>
      </div>
      <DataSourcePanel />
      {error && <div className="alert error">{error}</div>}
      {notice && <p className="notice">{notice}</p>}
      {customers === null ? (
        <p className="muted">客户档案加载中…</p>
      ) : customers.length === 0 ? (
        <div className="empty-state">
          <p>还没有客户档案，点【导入示例客户】导入演示数据。</p>
        </div>
      ) : (
        <div className="db-table-wrap">
          <table className="db-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>称呼</th>
                <th>联系许可</th>
                <th>长期喜好</th>
                <th>购买记录简述</th>
                <th>更新时间</th>
              </tr>
            </thead>
            <tbody>
              {customers.map((customer) => (
                <tr key={customer.customer_id}>
                  <td>{customer.customer_id}</td>
                  <td>{displayName(customer)}</td>
                  <td>{contactPermission(customer)}</td>
                  <td className="db-cell-wide">{longTermPreferences(customer)}</td>
                  <td>{purchaseSummary(customer)}</td>
                  <td>{(customer.updated_at ?? '').slice(0, 16)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
