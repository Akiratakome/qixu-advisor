import type { Conversation, Customer, ModelSettings, WritingSettings } from '../api'
import CustomerPanel from './CustomerPanel'
import ModelConfig from './ModelConfig'

const LANGUAGE_OPTIONS: Array<{ label: string; value: WritingSettings['output_language'] }> = [
  { label: '中文', value: 'zh-CN' },
  { label: 'English', value: 'en' },
]
const TONE_OPTIONS: Array<{ label: string; value: WritingSettings['tone'] }> = [
  { label: '自然', value: 'natural' },
  { label: '温和', value: 'warm' },
  { label: '直接', value: 'direct' },
]
const LENGTH_OPTIONS: Array<{ label: string; value: WritingSettings['length'] }> = [
  { label: '简短', value: 'short' },
  { label: '标准', value: 'standard' },
]
const GOAL_OPTIONS: Array<{ label: string; value: WritingSettings['goal'] }> = [
  { label: '按场景默认', value: null },
  { label: '回答问题', value: 'answer' },
  { label: '帮助选择', value: 'recommend' },
  { label: '提出下一步', value: 'next_step' },
]

function conversationLabel(conversation: Conversation, customers: Customer[]): string {
  const time = (conversation.updated_at ?? conversation.created_at ?? '').slice(0, 16)
  const scenario = conversation.scenario ?? '场景未定'
  const customer = customers.find((item) => item.customer_id === conversation.customer_id)
  const customerLabel = customer
    ? ((customer.profile.display_name as string | undefined) ??
      (customer.profile.name as string | undefined) ??
      conversation.customer_id)
    : '无档案'
  return `${time} · ${scenario} · ${customerLabel}`
}

interface SidebarProps {
  open: boolean
  onClose: () => void
  conversations: Conversation[] | null
  selectedId: string | null
  onSelect: (id: string) => void
  onCreate: () => void
  creating: boolean
  settings: WritingSettings
  onSettingsChange: (settings: WritingSettings) => void
  model: ModelSettings | null
  onModelChanged: () => void
  customers: Customer[]
  onCustomersChanged: () => void
  prefCustomerId: string | null
  onPrefCustomerChange: (id: string | null) => void
}

export default function Sidebar({
  open,
  onClose,
  conversations,
  selectedId,
  onSelect,
  onCreate,
  creating,
  settings,
  onSettingsChange,
  model,
  onModelChanged,
  customers,
  onCustomersChanged,
  prefCustomerId,
  onPrefCustomerChange,
}: SidebarProps) {
  return (
    <>
      {open && <div className="sidebar-backdrop" onClick={onClose} />}
      <aside className={`sidebar ${open ? 'open' : ''}`}>
        <a className="database-link" href="/?view=database">
          📇 数据库
        </a>
        <details className="sidebar-details" open>
          <summary>会话</summary>
          <div className="sidebar-head">
            <button className="btn mini primary" type="button" disabled={creating} onClick={onCreate}>
              {creating ? '新建中…' : '新建会话'}
            </button>
          </div>
          {conversations === null ? (
            <p className="muted">会话加载中…</p>
          ) : conversations.length === 0 ? (
            <p className="muted">暂无会话，点击「新建会话」开始。</p>
          ) : (
            <ul className="conversation-list">
              {conversations.map((conversation) => (
                <li key={conversation.conversation_id}>
                  <button
                    className={`conversation-item ${conversation.conversation_id === selectedId ? 'active' : ''}`}
                    type="button"
                    title={conversationLabel(conversation, customers)}
                    onClick={() => onSelect(conversation.conversation_id)}
                  >
                    <span className="conversation-name">{conversationLabel(conversation, customers)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </details>

        <details className="sidebar-details">
          <summary>客户资料</summary>
          <CustomerPanel
            customers={customers}
            onChanged={onCustomersChanged}
            prefCustomerId={prefCustomerId}
            onPrefCustomerChange={onPrefCustomerChange}
          />
        </details>

        <details className="sidebar-details">
          <summary>写作设置</summary>
          <label className="field">
            <span className="field-label">输出语言</span>
            <select
              value={settings.output_language}
              onChange={(event) =>
                onSettingsChange({ ...settings, output_language: event.target.value as WritingSettings['output_language'] })
              }
            >
              {LANGUAGE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span className="field-label">语气</span>
            <select
              value={settings.tone}
              onChange={(event) =>
                onSettingsChange({ ...settings, tone: event.target.value as WritingSettings['tone'] })
              }
            >
              {TONE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span className="field-label">篇幅</span>
            <select
              value={settings.length}
              onChange={(event) =>
                onSettingsChange({ ...settings, length: event.target.value as WritingSettings['length'] })
              }
            >
              {LENGTH_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span className="field-label">本次目标</span>
            <select
              value={settings.goal ?? ''}
              onChange={(event) => {
                const value = event.target.value
                onSettingsChange({
                  ...settings,
                  goal: (value === '' ? null : value) as WritingSettings['goal'],
                })
              }}
            >
              {GOAL_OPTIONS.map((option) => (
                <option key={option.label} value={option.value ?? ''}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <p className="muted">设置保存在本机浏览器，生成时随请求传入。</p>
        </details>

        <details className="sidebar-details">
          <summary>模型配置</summary>
          <ModelConfig key={`${model?.base_url ?? ''}|${model?.model ?? ''}`} model={model} onChanged={onModelChanged} />
        </details>
      </aside>
    </>
  )
}
