import { useCallback, useEffect, useState } from 'react'

import type {
  AnalyzeResult,
  Conversation,
  ConversationDetail,
  Customer,
  Draft,
  Generation,
  ModelSettings,
  WritingSettings,
} from './api'
import { DEFAULT_SETTINGS, api, errorMessage } from './api'
import { SCENARIOS, isScenario, parseChatLines } from './chat'
import AnalysisPanel from './components/AnalysisPanel'
import Composer from './components/Composer'
import DraftCard from './components/DraftCard'
import MessageStream from './components/MessageStream'
import Sidebar from './components/Sidebar'

const SETTINGS_STORAGE_KEY = 'qixu.writing-settings'

type PendingAction = { kind: 'switch-conversation'; id: string } | { kind: 'generate' } | null

function loadSettings(): WritingSettings {
  try {
    const raw = localStorage.getItem(SETTINGS_STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<WritingSettings>
      return { ...DEFAULT_SETTINGS, ...parsed }
    }
  } catch {
    // 本地设置损坏时回退默认值。
  }
  return DEFAULT_SETTINGS
}

function byUpdatedDesc(first: Conversation, second: Conversation): number {
  return (second.updated_at ?? '').localeCompare(first.updated_at ?? '')
}

export default function App() {
  const [conversations, setConversations] = useState<Conversation[] | null>(null)
  const [customers, setCustomers] = useState<Customer[]>([])
  const [model, setModel] = useState<ModelSettings | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<ConversationDetail | null>(null)
  const [creating, setCreating] = useState(false)
  const [posting, setPosting] = useState(false)
  const [composer, setComposer] = useState('')
  const [settings, setSettings] = useState<WritingSettings>(loadSettings)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [prefCustomerId, setPrefCustomerId] = useState<string | null>(null)

  const [analysis, setAnalysis] = useState<AnalyzeResult | null>(null)
  const [scenario, setScenario] = useState<string>('')
  const [needText, setNeedText] = useState('')
  const [analyzing, setAnalyzing] = useState(false)
  const [analysisError, setAnalysisError] = useState<string | null>(null)
  const [generation, setGeneration] = useState<Generation | null>(null)
  const [generating, setGenerating] = useState(false)
  const [generationError, setGenerationError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [banner, setBanner] = useState<string | null>(null)
  const [dirtyDraftIds, setDirtyDraftIds] = useState<Set<number>>(new Set())
  const [pendingAction, setPendingAction] = useState<PendingAction>(null)

  useEffect(() => {
    localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(settings))
  }, [settings])

  // 刷新前拦截：有未保存修改时给出浏览器原生提示。
  useEffect(() => {
    function handleBeforeUnload(event: BeforeUnloadEvent) {
      if (dirtyDraftIds.size > 0) {
        event.preventDefault()
        event.returnValue = ''
      }
    }
    window.addEventListener('beforeunload', handleBeforeUnload)
    return () => window.removeEventListener('beforeunload', handleBeforeUnload)
  }, [dirtyDraftIds])

  const handleDraftDirty = useCallback((draftId: number, dirty: boolean) => {
    setDirtyDraftIds((current) => {
      const next = new Set(current)
      if (dirty) {
        next.add(draftId)
      } else {
        next.delete(draftId)
      }
      return next
    })
  }, [])

  useEffect(() => {
    void (async () => {
      try {
        const [conversationList, customerList, modelSettings] = await Promise.all([
          api.conversations.list(),
          api.customers.list(),
          api.settings.model(),
        ])
        const sorted = [...conversationList].sort(byUpdatedDesc)
        setConversations(sorted)
        setCustomers(customerList)
        setModel(modelSettings)
        if (sorted.length > 0) {
          setSelectedId(sorted[0].conversation_id)
        }
      } catch (error) {
        setBanner(errorMessage(error))
        setConversations([])
      }
    })()
  }, [])

  const loadDetail = useCallback(async (conversationId: string): Promise<ConversationDetail | null> => {
    try {
      return await api.conversations.get(conversationId)
    } catch (error) {
      setBanner(errorMessage(error))
      return null
    }
  }, [])

  // 切换会话：重载消息；分析与草稿重置在点击事件中完成。
  useEffect(() => {
    if (!selectedId) {
      return
    }
    let cancelled = false
    void (async () => {
      const loaded = await loadDetail(selectedId)
      if (!cancelled && loaded) {
        setDetail(loaded)
        setPrefCustomerId(loaded.customer_id ?? null)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [selectedId, loadDetail])

  function handleSelectConversation(id: string) {
    if (id === selectedId) {
      setSidebarOpen(false)
      return
    }
    if (dirtyDraftIds.size > 0) {
      setSidebarOpen(false)
      setPendingAction({ kind: 'switch-conversation', id })
      return
    }
    switchConversation(id)
  }

  function switchConversation(id: string) {
    setSelectedId(id)
    setAnalysis(null)
    setScenario('')
    setNeedText('')
    setAnalysisError(null)
    setGeneration(null)
    setGenerationError(null)
    setComposer('')
    setNotice(null)
    setPendingAction(null)
    setDirtyDraftIds(new Set())
    setSidebarOpen(false)
  }

  async function handleCreateConversation() {
    setCreating(true)
    try {
      const created = await api.conversations.create()
      const refreshed = await api.conversations.list()
      setConversations([...refreshed].sort(byUpdatedDesc))
      setSelectedId(created.conversation_id)
      setBanner(null)
    } catch (error) {
      setBanner(errorMessage(error))
    } finally {
      setCreating(false)
    }
  }

  async function handleCustomerChange(customerId: string) {
    if (!detail || customerId === (detail.customer_id ?? '')) {
      return
    }
    try {
      const patched = await api.conversations.patch(detail.conversation_id, {
        expected_version: detail.version,
        customer_id: customerId,
      })
      setDetail({ ...detail, version: patched.version, customer_id: patched.customer_id })
      setPrefCustomerId(patched.customer_id ?? null)
      setNotice('客户已关联到本会话。')
    } catch (error) {
      setBanner(errorMessage(error))
    }
  }

  async function postLines(target: ConversationDetail, lines: Array<{ role: string; content: string }>): Promise<ConversationDetail | null> {
    try {
      for (const line of lines) {
        await api.conversations.postMessage(target.conversation_id, {
          role: line.role,
          content: line.content,
          source: line.role === 'advisor' ? 'workbench' : 'manual',
        })
      }
      return await loadDetail(target.conversation_id)
    } catch (error) {
      setBanner(errorMessage(error))
      return null
    }
  }

  async function handleAddMessages() {
    if (!detail) {
      return
    }
    const lines = parseChatLines(composer)
    if (lines.length === 0) {
      return
    }
    setPosting(true)
    setBanner(null)
    const loaded = await postLines(detail, lines)
    if (loaded) {
      setComposer('')
      setDetail(loaded)
      setNotice('消息已写入会话。')
    }
    setPosting(false)
    if (loaded) {
      await analyzeConversation(loaded)
    }
  }

  const runAnalysis = useCallback(
    async (
      history: Array<{ role: string; content: string }>,
      customer: Customer | undefined,
      silentRetry: boolean,
    ) => {
      setAnalyzing(true)
      setAnalysisError(null)
      setBanner(null)
      const run = () =>
        api.analyze({
          conversation_history: history,
          client_information: customer ? (customer.profile as Record<string, unknown>) : {},
        })
      try {
        let result: AnalyzeResult
        if (silentRetry) {
          try {
            result = await run()
          } catch {
            // 自动分析首次失败：静默重试一次。
            result = await run()
          }
        } else {
          result = await run()
        }
        setAnalysis(result)
        setScenario(isScenario(result.scenario) ? result.scenario : SCENARIOS[0])
        setNeedText(result.current_need)
        setAnalysisError(null)
      } catch (error) {
        setAnalysisError(errorMessage(error))
      } finally {
        setAnalyzing(false)
      }
    },
    [],
  )

  async function analyzeConversation(target: ConversationDetail, silentRetry = true) {
    const customer = customers.find((item) => item.customer_id === target.customer_id)
    await runAnalysis(
      target.messages.map((message) => ({ role: message.role, content: message.content })),
      customer,
      silentRetry,
    )
  }

  const analyzeDraft = useCallback(
    async (composerText: string, silentRetry = true) => {
      if (!detail) {
        return
      }
      const draftLines = parseChatLines(composerText)
      if (draftLines.length === 0) {
        return
      }
      const customer = customers.find((item) => item.customer_id === detail.customer_id)
      const history = [
        ...detail.messages.map((message) => ({ role: message.role, content: message.content })),
        ...draftLines.map((line) => ({ role: line.role, content: line.content })),
      ]
      await runAnalysis(history, customer, silentRetry)
    },
    [detail, customers, runAnalysis],
  )

  // 输入停止约 1.2 秒后自动理解：内容非空且与最后一条已添加消息不同才触发。
  useEffect(() => {
    const value = composer.trim()
    if (!value || !detail) {
      return
    }
    const lastMessage = detail.messages.length > 0 ? detail.messages[detail.messages.length - 1].content.trim() : ''
    if (value === lastMessage) {
      return
    }
    const timer = window.setTimeout(() => {
      void analyzeDraft(value)
    }, 1200)
    return () => window.clearTimeout(timer)
  }, [composer, detail, analyzeDraft])

  function handleRetryAnalysis() {
    if (!detail) {
      return
    }
    const value = composer.trim()
    if (value) {
      void analyzeDraft(value, false)
    } else {
      void analyzeConversation(detail, false)
    }
  }

  function requestGenerate() {
    if (dirtyDraftIds.size > 0) {
      setPendingAction({ kind: 'generate' })
      return
    }
    void runGenerate()
  }

  async function runGenerate() {
    if (!detail || !analysis) {
      return
    }
    setGenerating(true)
    setGenerationError(null)
    setBanner(null)
    let current = detail
    // 输入框有未添加的内容：先生成消息落库，再走生成流程。
    const pendingText = composer.trim()
    const lastMessage = current.messages.length > 0 ? current.messages[current.messages.length - 1].content.trim() : ''
    if (pendingText && pendingText !== lastMessage) {
      const lines = parseChatLines(pendingText)
      if (lines.length > 0) {
        const loaded = await postLines(current, lines)
        if (!loaded) {
          setGenerating(false)
          return
        }
        current = loaded
        setDetail(loaded)
        setComposer('')
        setNotice('输入内容已写入会话。')
      }
    }
    try {
      const patched = await api.conversations.patch(current.conversation_id, {
        expected_version: current.version,
        scenario: scenario || analysis.scenario,
        settings,
        current_need: needText.trim() || analysis.current_need,
      })
      const result = await api.conversations.createGeneration(
        current.conversation_id,
        { expected_version: patched.version, settings },
        `v${patched.version}-${Date.now()}`,
      )
      setGeneration(result)
      setDetail({ ...current, version: patched.version, scenario: patched.scenario })
      setDirtyDraftIds(new Set())
    } catch (error) {
      setGenerationError(errorMessage(error))
    } finally {
      setGenerating(false)
    }
  }

  function confirmPendingAction() {
    const action = pendingAction
    setPendingAction(null)
    setDirtyDraftIds(new Set())
    if (action?.kind === 'switch-conversation') {
      switchConversation(action.id)
    } else if (action?.kind === 'generate') {
      void runGenerate()
    }
  }

  const refreshModelStatus = useCallback(async () => {
    try {
      setModel(await api.settings.model())
    } catch (error) {
      setBanner(errorMessage(error))
    }
  }, [])

  function handleDraftUpdated(updated: Draft) {
    setGeneration((current) => {
      if (!current) {
        return current
      }
      return {
        ...current,
        drafts: current.drafts.map((draft) =>
          draft.draft_id === updated.draft_id
            ? { ...draft, revision: updated.revision, text: updated.text, source: updated.source }
            : draft,
        ),
      }
    })
  }

  const hasDrafts = generation !== null && generation.business_status === 'success' && generation.drafts.length > 0

  return (
    <div className="app-shell">
      <Sidebar
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        conversations={conversations}
        selectedId={selectedId}
        onSelect={handleSelectConversation}
        onCreate={() => void handleCreateConversation()}
        creating={creating}
        settings={settings}
        onSettingsChange={setSettings}
        model={model}
        onModelChanged={() => void refreshModelStatus()}
        customers={customers}
        prefCustomerId={prefCustomerId}
        onPrefCustomerChange={setPrefCustomerId}
      />
      <main className="main-area">
        <header className="top-bar">
          <button
            className="hamburger"
            type="button"
            aria-label="打开侧栏"
            onClick={() => setSidebarOpen((value) => !value)}
          >
            ☰
          </button>
          <span className="bar-brand">
            栖序 QIXU<span className="bar-sub"> · 香水顾问写作助手 · 资料均为虚构</span>
          </span>
          <span className="spacer" />
          {detail && (
            <label className="field inline">
              <span className="field-label">客户</span>
              <select
                className="compact-select"
                value={detail.customer_id ?? ''}
                onChange={(event) => void handleCustomerChange(event.target.value)}
              >
                <option value="">未选择客户</option>
                {customers.map((customer) => (
                  <option key={customer.customer_id} value={customer.customer_id}>
                    {((customer.profile.display_name as string | undefined) ??
                      (customer.profile.name as string | undefined) ??
                      customer.customer_id)}
                  </option>
                ))}
              </select>
            </label>
          )}
          <button className="btn mini" type="button" disabled={creating} onClick={() => void handleCreateConversation()}>
            新建会话
          </button>
        </header>
        {banner && <div className="alert error">{banner}</div>}
        {pendingAction && (
          <div className="alert warning unsaved-guard">
            <span>当前候选卡有未保存的修改，继续操作将丢失这些本地修改；已保存的内容不受影响。</span>
            <div className="unsaved-guard-actions">
              <button className="btn mini danger" type="button" onClick={confirmPendingAction}>
                放弃修改并继续
              </button>
              <button className="btn mini" type="button" onClick={() => setPendingAction(null)}>
                继续编辑
              </button>
            </div>
          </div>
        )}
        {!detail ? (
          <div className="empty-state">
            {conversations === null ? (
              <p>会话加载中…</p>
            ) : conversations.length === 0 ? (
              <>
                <p>还没有会话。</p>
                <p className="muted">新建一个会话，粘贴对话后开始分析与写作。</p>
                <button
                  className="btn primary"
                  type="button"
                  disabled={creating}
                  onClick={() => void handleCreateConversation()}
                >
                  新建会话
                </button>
              </>
            ) : (
              <p className="muted">请在左侧选择一个会话。</p>
            )}
          </div>
        ) : (
          <div className="workspace">
            <section className="panel chat-panel">
              <MessageStream messages={detail.messages} />
              <Composer
                value={composer}
                onChange={setComposer}
                onSubmit={() => void handleAddMessages()}
                busy={posting}
                disabled={false}
              />
              {notice && <p className="notice">{notice}</p>}
            </section>
            <AnalysisPanel
              analysis={analysis}
              scenario={scenario}
              onScenarioChange={setScenario}
              needText={needText}
              onNeedTextChange={setNeedText}
              analyzing={analyzing}
              analysisError={analysisError}
              onRetryAnalysis={handleRetryAnalysis}
              generating={generating}
              generationError={generationError}
              onGenerate={requestGenerate}
              generation={generation}
            />
            {hasDrafts && (
              <section className="panel drafts-section">
                <div className="panel-head">
                  <h2>三条候选</h2>
                  <span className="muted">保存与复制均不会发送微信 · 请核对人物、价格、规格和承诺后再选用</span>
                </div>
                <div className="drafts-grid">
                  {generation.drafts.map((draft, index) => (
                    <DraftCard
                      key={draft.draft_id}
                      draft={draft}
                      index={index + 1}
                      onDraftUpdated={handleDraftUpdated}
                      onNotice={setNotice}
                      onDirtyChange={handleDraftDirty}
                    />
                  ))}
                </div>
              </section>
            )}
          </div>
        )}
      </main>
    </div>
  )
}
