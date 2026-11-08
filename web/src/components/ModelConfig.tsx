import { useState } from 'react'

import type { ModelSettings, ModelSettingsIn } from '../api'
import { api, errorMessage } from '../api'

const DEFAULT_BASE_URL = 'https://api.deepseek.com'
const DEFAULT_MODEL = 'deepseek-flash'

interface ModelConfigProps {
  model: ModelSettings | null
  onChanged: () => void
}

export default function ModelConfig({ model, onChanged }: ModelConfigProps) {
  const [baseUrl, setBaseUrl] = useState(model?.base_url || DEFAULT_BASE_URL)
  const [modelName, setModelName] = useState(model?.model || DEFAULT_MODEL)
  const [apiKey, setApiKey] = useState('')
  const [temperature, setTemperature] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  async function handleSave() {
    const trimmedUrl = baseUrl.trim()
    const trimmedModel = modelName.trim()
    if (!trimmedUrl || !trimmedModel) {
      setSaveError('接口地址与模型不能为空。')
      return
    }
    const parsedTemperature = temperature.trim() === '' ? null : Number(temperature)
    if (parsedTemperature !== null && (Number.isNaN(parsedTemperature) || parsedTemperature < 0 || parsedTemperature > 2)) {
      setSaveError('温度须在 0–2 之间；留空表示不修改。')
      return
    }
    setSaving(true)
    setSaveError(null)
    setSaved(false)
    const body: ModelSettingsIn = { base_url: trimmedUrl, model: trimmedModel }
    if (apiKey.trim()) {
      body.api_key = apiKey.trim()
    }
    if (parsedTemperature !== null) {
      body.temperature = parsedTemperature
    }
    try {
      await api.settings.putModel(body)
      setSaved(true)
      setApiKey('')
      onChanged()
    } catch (error) {
      setSaveError(errorMessage(error))
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="sidebar-section">
      <h3>模型配置</h3>
      <label className="field">
        <span className="field-label">接口地址 base_url</span>
        <input
          type="text"
          value={baseUrl}
          onChange={(event) => setBaseUrl(event.target.value)}
          placeholder={DEFAULT_BASE_URL}
        />
      </label>
      <label className="field">
        <span className="field-label">模型 model</span>
        <input
          type="text"
          value={modelName}
          onChange={(event) => setModelName(event.target.value)}
          placeholder={DEFAULT_MODEL}
        />
      </label>
      <label className="field">
        <span className="field-label">API 密钥（留空保持现有）</span>
        <input
          type="password"
          value={apiKey}
          onChange={(event) => setApiKey(event.target.value)}
          placeholder="留空保持现有密钥"
          autoComplete="off"
        />
      </label>
      <label className="field">
        <span className="field-label">温度（可选，0–2；留空不修改）</span>
        <input
          type="number"
          min={0}
          max={2}
          step={0.1}
          value={temperature}
          onChange={(event) => setTemperature(event.target.value)}
          placeholder="默认不传"
        />
      </label>
      <button className="btn primary" type="button" disabled={saving} onClick={() => void handleSave()}>
        {saving ? '保存中…' : '保存配置'}
      </button>
      {saved && <p className="notice">配置已保存。</p>}
      {saveError && <div className="alert error">{saveError}（未自动重试）</div>}
      <div className="model-status">
        {model === null ? (
          <p className="muted">状态加载中…</p>
        ) : (
          <>
            <p className="muted">已配置：{model.configured ? '是' : '否'}</p>
            {model.api_key_set !== undefined && (
              <p className="muted">API 密钥：{model.api_key_set ? '已设置' : '未设置'}</p>
            )}
            {model.source !== undefined && model.source !== null && (
              <p className="muted">配置来源：{model.source}</p>
            )}
            {model.model && <p className="muted">当前模型：{model.model}</p>}
          </>
        )}
      </div>
      <p className="muted">密钥仅保存在本机运行库，请自行评估安全。品牌、客户与业务资料均为虚构。</p>
    </section>
  )
}
