import { useEffect, useState } from 'react'

import { api, errorMessage } from '../api'

export default function DataSourcePanel() {
  const [url, setUrl] = useState('')
  const [key, setKey] = useState('')
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [notReady, setNotReady] = useState(false)

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const current = await api.datasource.get()
        if (!cancelled) {
          setUrl(current.supabase_url ?? '')
        }
      } catch {
        // 端点未落地或未配置：保持空白输入，保存/测试时再给出友好提示。
        if (!cancelled) {
          setNotReady(true)
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  function requestBody() {
    const body: { supabase_url?: string; supabase_service_key?: string } = {}
    if (url.trim()) {
      body.supabase_url = url.trim()
    }
    if (key.trim()) {
      body.supabase_service_key = key.trim()
    }
    return body
  }

  async function handleSave() {
    setSaving(true)
    setError(null)
    setNotice(null)
    try {
      await api.datasource.put(requestBody())
      setKey('')
      setNotice('外部数据源已保存。')
      setNotReady(false)
    } catch (saveError) {
      if (saveError instanceof Error && saveError.name === 'ApiError' && (saveError as { status?: number }).status === 404) {
        setNotReady(true)
        setError('后端未就绪：外部数据源接口尚未部署。')
      } else {
        setError(errorMessage(saveError))
      }
    } finally {
      setSaving(false)
    }
  }

  async function handleTest() {
    setTesting(true)
    setError(null)
    setNotice(null)
    try {
      const result = await api.datasource.test(requestBody())
      setNotice(result.ok ? (result.message || '连接正常。') : `连接失败：${result.message || '请检查地址与密钥'}。`)
    } catch (testError) {
      if (testError instanceof Error && testError.name === 'ApiError' && (testError as { status?: number }).status === 404) {
        setNotReady(true)
        setError('后端未就绪：外部数据源接口尚未部署。')
      } else {
        setError(errorMessage(testError))
      }
    } finally {
      setTesting(false)
    }
  }

  return (
    <details className="datasource-panel">
      <summary>外部数据源</summary>
      <p className="muted">可接入公司客户库（如 Supabase 或自建服务）；个人用户也可以不配置——不配置时使用本地客户档案。</p>
      {notReady && <p className="muted">后端未就绪：保存与测试暂不可用。</p>}
      <label className="field">
        <span className="field-label">外部数据源地址</span>
        <input type="text" value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://你的服务地址" />
      </label>
      <label className="field">
        <span className="field-label">访问密钥（留空保持现有）</span>
        <input
          type="password"
          value={key}
          onChange={(event) => setKey(event.target.value)}
          placeholder="留空保持现有密钥"
          autoComplete="off"
        />
      </label>
      <div className="datasource-actions">
        <button className="btn mini primary" type="button" disabled={saving || notReady} onClick={() => void handleSave()}>
          {saving ? '保存中…' : notReady ? '后端未就绪' : '保存'}
        </button>
        <button className="btn mini" type="button" disabled={testing || notReady} onClick={() => void handleTest()}>
          {testing ? '测试中…' : notReady ? '后端未就绪' : '测试连接'}
        </button>
      </div>
      {notice && <p className="notice">{notice}</p>}
      {error && <div className="alert error">{error}</div>}
    </details>
  )
}
