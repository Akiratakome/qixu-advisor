import { useCallback, useEffect, useMemo, useState } from 'react'

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
  const [analyzing, setAnalyzing] = useState(false)
  const [analysisError, setAnalysisError] = useState<string | null>(null)
  const [generation, setGeneration] = useState<Generation | null>(null)
  const [generating, setGenerating] = useState(false)
  const [generationError, setGenerationError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [banner, setBanner] = useState<string | null>(null)

  useEffect(() => {
    localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(settings))
  }, [settings])

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

  // 切换会话：重载消息；分析与草稿重置在点击事件中完成（新会话不沿用上一会话上下文）。
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
      return
    }
    setSelectedId(id)
    setAnalysis(null)
    setScenario('')
    setAnalysisError(null)
    setGeneration(null)
    setGenerationError(null)
    setComposer('')
    setNotice(null)
  }

  async function refreshDetail() {
    if (!detail) {
      return
    }
    const loaded = await loadDetail(detail.conversation_id)
    if (loaded) {
      setDetail(loaded)
    }
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
    try {
      for (const line of lines) {
        await api.conversations.postMessage(detail.conversation_id, {
          role: line.role,
          content: line.content,
          source: line.role === 'advisor' ? 'workbench' : 'manual',
        })
      }
      setComposer('')
      await refreshDetail()
      setNotice('消息已写入会话。')
    } catch (error) {
      setBanner(errorMessage(error))
    } finally {
      setPosting(false)
    }
  }

  async function handleAnalyze() {
    if (!detail) {
      return
    }
    setAnalyzing(true)
    setAnalysisError(null)
    setGeneration(null)
    setBanner(null)
    const customer = customers.find((item) => item.customer_id === detail.customer_id)
    try {
      const result = await api.analyze({
        conversation_history: detail.messages.map((message) => ({
          role: message.role,
          content: message.content,
        })),
        client_information: customer ? (customer.profile as Record<string, unknown>) : {},
      })
      setAnalysis(result)
      setScenario(isScenario(result.scenario) ? result.scenario : SCENARIOS[0])
    } catch (error) {
      setAnalysisError(errorMessage(error))
    } finally {
      setAnalyzing(false)
    }
  }

  async function handleGenerate() {
    if (!detail || !analysis) {
      return
    }
    setGenerating(true)
    setGenerationError(null)
    setBanner(null)
    try {
      const patched = await api.conversations.patch(detail.conversation_id, {
        expected_version: detail.version,
        scenario: scenario || analysis.scenario,
        settings,
        current_need: analysis.current_need,
      })
      const result = await api.conversations.createGeneration(
        detail.conversation_id,
        { expected_version: patched.version, settings },
        `v${patched.version}-${Date.now()}`,
      )
      setGeneration(result)
      setDetail({ ...detail, version: patched.version, scenario: patched.scenario })
    } catch (error) {
      setGenerationError(errorMessage(error))
    } finally {
      setGenerating(false)
    }
  }

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
  const conversationTitle = useMemo(() => {
    if (!detail) {
      return '会话'
    }
    const customer = customers.find((item) => item.customer_id === detail.customer_id)
    const name = customer ? ((customer.profile.display_name as string | undefined) ?? '客户') : '客户'
    return `${name} · ${detail.scenario ?? '场景未定'}`
  }, [detail, customers])

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
        customers={customers}
        prefCustomerId={prefCustomerId}
        onPrefCustomerChange={setPrefCustomerId}
      />
      <main className="main-area">
        <header className="brand">
          <div className="brand-row">
            <button
              className="hamburger"
              type="button"
              aria-label="打开侧栏"
              onClick={() => setSidebarOpen((value) => !value)}
            >
              ☰
            </button>
            <div>
              <h1 className="brand-title">栖序 QIXU</h1>
              <p className="brand-sub">香水顾问写作助手 · 资料均为虚构</p>
            </div>
          </div>
        </header>
        {banner && <div className="alert error">{banner}</div>}
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
            <section className="panel">
              <div className="panel-head">
                <h2>{conversationTitle}</h2>
              </div>
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
              analyzing={analyzing}
              analysisError={analysisError}
              onAnalyze={() => void handleAnalyze()}
              generating={generating}
              generationError={generationError}
              onGenerate={() => void handleGenerate()}
              generation={generation}
            />
            {hasDrafts && (
              <section className="panel drafts-section">
                <div className="panel-head">
                  <h2>三条候选</h2>
                  <span className="muted">结构检查通过不代表内容已经通过人工评价；请核对人物、价格、规格和承诺。</span>
                </div>
                {generation.drafts.map((draft, index) => (
                  <DraftCard
                    key={draft.draft_id}
                    draft={draft}
                    index={index + 1}
                    onDraftUpdated={handleDraftUpdated}
                    onNotice={setNotice}
                  />
                ))}
              </section>
            )}
          </div>
        )}
      </main>
    </div>
  )
}
