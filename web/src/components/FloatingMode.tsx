import { useCallback, useEffect, useState } from 'react'

import type { Customer, Generation } from '../api'
import { ApiError, DEFAULT_SETTINGS, api, errorMessage } from '../api'
import { SCENARIOS } from '../chat'
import DraftCard from './DraftCard'

// 悬浮卡片模式（?floating=1）：极简窗口——无侧栏、无顶栏标题；
// 粘贴客户消息回车生成，三条候选竖排，复制后整卡高亮。
// 不恢复任何已保存会话：每次打开都是干净状态，生成时始终新建会话；
// 窗口最小化/关闭由桌面壳负责，前端只渲染折叠态与触发 window.close()。

const BUSINESS_LABELS: Record<string, string> = {
  needs_input: '需要补充资料',
  contact_blocked: '已停止：客户明确拒绝联系',
  technical_failure: '生成失败',
  interrupted: '生成未完成，请重试',
}

// 桌面壳 preload 注入的桥接：截图识别与识别结果回填（无桥接时按钮隐藏）。
declare global {
  interface Window {
    qixu?: {
      captureAndOcr?: () => void
      onOcrText?: (callback: (text: string) => void) => void
    }
  }
}

export default function FloatingMode() {
  const [customers, setCustomers] = useState<Customer[]>([])
  // 默认场景取「产品推荐」：只凭消息内容即可生成；生日与节庆还需祝福缘由，活动邀请还需具体活动。
  const [scenario, setScenario] = useState<string>('产品推荐')
  const [customerId, setCustomerId] = useState('')
  const [optionsOpen, setOptionsOpen] = useState(false)
  const [input, setInput] = useState('')
  const [generating, setGenerating] = useState(false)
  const [generation, setGeneration] = useState<Generation | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [minimized, setMinimized] = useState(false)

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const list = await api.customers.list()
        if (!cancelled) {
          setCustomers(list)
        }
      } catch {
        // 客户列表不可用时仍可生成（不使用档案）。
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  // 一次性轻提示与错误：数秒后自动消失，不渲染常驻错误条。
  useEffect(() => {
    if (!notice && !error) {
      return
    }
    const timer = window.setTimeout(() => {
      setNotice(null)
      setError(null)
    }, 5000)
    return () => window.clearTimeout(timer)
  }, [notice, error])

  // 桌面壳 OCR：注册回填回调（识别文本只填入输入框，不自动生成）。
  useEffect(() => {
    const bridge = window.qixu
    if (!bridge?.onOcrText) {
      return
    }
    bridge.onOcrText((text) => {
      if (typeof text === 'string' && text.trim()) {
        setInput(text)
      }
    })
  }, [])

  const ocrAvailable = typeof window.qixu?.captureAndOcr === 'function'

  function resetToCleanState() {
    setGeneration(null)
    setError(null)
    setNotice('会话已重置')
  }

  async function handleGenerate() {
    const text = input.trim()
    if (!text) {
      return
    }
    setGenerating(true)
    setError(null)
    setNotice(null)
    try {
      // 每次生成都新建会话，不复用旧会话，避免历史会话失效造成 404。
      const created = await api.conversations.create({
        scenario,
        customer_id: customerId || undefined,
      })
      const targetId = created.conversation_id
      await api.conversations.postMessage(targetId, { role: 'client', content: text, source: 'manual' })
      const detail = await api.conversations.get(targetId)
      const patched = await api.conversations.patch(targetId, {
        expected_version: detail.version,
        scenario,
        customer_id: customerId || undefined,
        settings: DEFAULT_SETTINGS,
        current_need: text,
        occasion: scenario === '生日与节庆' ? text : undefined,
      })
      const result = await api.conversations.createGeneration(
        targetId,
        { expected_version: patched.version, settings: DEFAULT_SETTINGS },
        `v${patched.version}-${Date.now()}`,
      )
      setGeneration(result)
      setInput('')
      setMinimized(false)
    } catch (generateError) {
      if (generateError instanceof ApiError && generateError.status === 404) {
        // 内容已不存在：重置为干净状态，只给一次性轻提示。
        resetToCleanState()
      } else {
        setError(errorMessage(generateError))
      }
    } finally {
      setGenerating(false)
    }
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      void handleGenerate()
    }
  }

  function handleClose() {
    // Electron 主窗口 close → app.quit；浏览器中关闭当前页签（由浏览器策略决定）。
    window.close()
  }

  const handleDirtyChange = useCallback(() => {
    // 悬浮模式不跟踪未保存修改；保留回调以复用 DraftCard。
  }, [])

  function handleOutsideClick(event: React.MouseEvent<HTMLDivElement>) {
    // 仅点击卡片外部（深色背景区）最小化；卡片内按钮不受影响。
    if (event.target instanceof Element && !event.target.closest('.floating-glass')) {
      setMinimized(true)
    }
  }

  if (minimized) {
    return (
      <div className="floating-shell">
        <button className="floating-restore" type="button" onClick={() => setMinimized(false)}>
          栖序 QIXU · 点击展开
        </button>
      </div>
    )
  }

  return (
    <div className="floating-shell" onClick={handleOutsideClick}>
      <div className="floating-glass">
        <div className="floating-head">
          <span className="floating-brand">栖序 QIXU</span>
          <span className="spacer" />
          <button className="btn mini" type="button" onClick={() => setOptionsOpen((value) => !value)}>
            {optionsOpen ? '收起选项' : '选项'}
          </button>
          {ocrAvailable && (
            <button className="btn mini" type="button" onClick={() => window.qixu?.captureAndOcr?.()}>
              截图识别
            </button>
          )}
          <button className="btn mini" type="button" onClick={() => setMinimized(true)}>
            隐藏
          </button>
          <button className="btn mini" type="button" onClick={handleClose}>
            关闭
          </button>
        </div>
        {optionsOpen && (
          <div className="floating-options">
            <label className="field inline">
              <span className="field-label">场景</span>
              <select className="compact-select" value={scenario} onChange={(event) => setScenario(event.target.value)}>
                {SCENARIOS.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </select>
            </label>
            <label className="field inline">
              <span className="field-label">客户</span>
              <select className="compact-select" value={customerId} onChange={(event) => setCustomerId(event.target.value)}>
                <option value="">不使用档案</option>
                {customers.map((customer) => (
                  <option key={customer.customer_id} value={customer.customer_id}>
                    {((customer.profile.display_name as string | undefined) ??
                      (customer.profile.name as string | undefined) ??
                      customer.customer_id)}
                  </option>
                ))}
              </select>
            </label>
          </div>
        )}
        <textarea
          className="floating-input"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="和顾客的对话"
          rows={4}
          autoFocus
        />
        <p className="composer-subhint floating-subhint">记录顾问与顾客的对话，自动理解这轮需求</p>
        <div className="floating-actions">
          <button className="btn primary wide" type="button" disabled={generating || !input.trim()} onClick={() => void handleGenerate()}>
            {generating ? '生成中…' : '生成'}
          </button>
        </div>
        {error && <div className="alert error">{error}</div>}
        {notice && <p className="notice">{notice}</p>}
        {generation && generation.business_status === 'success' && generation.drafts.length > 0 && (
          <div className="floating-cards">
            <p className="floating-feedback-note">👍👎 反馈帮助我们改进后续回答</p>
            {generation.drafts.map((draft, index) => (
              <DraftCard
                key={draft.draft_id}
                draft={draft}
                index={index + 1}
                onDraftUpdated={() => undefined}
                onNotice={() => undefined}
                onDirtyChange={handleDirtyChange}
                minimal
              />
            ))}
          </div>
        )}
        {generation && generation.business_status && generation.business_status !== 'success' && (
          <div className="alert error">
            <strong>{BUSINESS_LABELS[generation.business_status] ?? generation.business_status}</strong>
            {generation.missing_fields.length > 0 && <div>待补充：{generation.missing_fields.join('、')}</div>}
            {generation.error && <div>{generation.error}</div>}
          </div>
        )}
      </div>
    </div>
  )
}
