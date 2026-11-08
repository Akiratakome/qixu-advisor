// 与 src/qixu_advisor/api_models.py 对齐的 typed fetch 客户端。
// 错误统一解析为 {error:{code,message,fields?},request_id}；网络层异常单独抛出。

export type OutputLanguage = 'zh-CN' | 'en'
export type Tone = 'natural' | 'warm' | 'direct'
export type Length = 'short' | 'standard'
export type Goal = 'answer' | 'recommend' | 'next_step'

export interface WritingSettings {
  output_language: OutputLanguage
  tone: Tone
  length: Length
  goal: Goal | null
}

export const DEFAULT_SETTINGS: WritingSettings = {
  output_language: 'zh-CN',
  tone: 'natural',
  length: 'standard',
  goal: null,
}

export interface Customer {
  customer_id: string
  version: number
  profile: Record<string, unknown>
  created_at?: string | null
  updated_at?: string | null
}

export interface Conversation {
  conversation_id: string
  customer_id: string | null
  scenario: string | null
  settings: Record<string, unknown>
  current_need: string | null
  budget_cny: number | null
  occasion: string | null
  event_id: string | null
  product_ids: string[]
  status: string
  version: number
  created_at?: string | null
  updated_at?: string | null
}

export interface Message {
  message_id: number
  conversation_id: string
  role: string
  content: string
  source: string
  external_id?: string | null
  created_at?: string | null
  conversation_version?: number | null
}

export interface ConversationDetail extends Conversation {
  messages: Message[]
}

export interface CatalogItem {
  sku_id: string
  product_id: string
  name: string
  volume_ml?: number | null
  price_cny: number
  currency?: string
  description?: string | null
  source?: string | null
}

export interface ModelSettings {
  configured: boolean
  provider: string
  model: string | null
  base_url: string | null
  missing: string[]
  // PUT 落地后由服务端补充：密钥是否已设置与配置来源。
  api_key_set?: boolean
  source?: string | null
}

export interface ModelSettingsIn {
  base_url?: string
  model?: string
  api_key?: string
  temperature?: number
}

export interface Draft {
  draft_id: number
  generation_id: string
  candidate_id: string
  revision: number
  text: string
  source: string
  created_at?: string | null
}

export interface Generation {
  generation_id: string
  conversation_id: string
  task_status: string
  business_status: string | null
  snapshot_version: number
  run_id: string | null
  case_id: string | null
  drafts: Draft[]
  missing_fields: string[]
  warnings: string[]
  error: string | null
  created_at?: string | null
  running: boolean
}

export interface DraftActionOut {
  action_id: number
  draft_revision_id: number
  action: string
  copied_text: string
  editor?: string | null
  created_at?: string | null
}

export interface Preference {
  preference_id: number
  subject: string
  kind: string
  original_text: string
  source: string
  explicit: boolean
  status: string
  created_at?: string | null
  updated_at?: string | null
}

export interface AnalyzeRequest {
  conversation_history: Array<{ role: string; content: string }>
  client_information: Record<string, unknown>
}

export interface AnalyzeResult {
  scenario: string
  current_need: string
  missing_questions: string[]
}

interface ErrorBody {
  error?: { code?: string; message?: string; fields?: Record<string, unknown> }
  request_id?: string
}

export class ApiError extends Error {
  status: number
  code: string
  fields?: Record<string, unknown>
  requestId?: string

  constructor(
    status: number,
    code: string,
    message: string,
    fields?: Record<string, unknown>,
    requestId?: string,
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.fields = fields
    this.requestId = requestId
  }
}

const BASE = '/api/v1'

async function request<T>(
  path: string,
  options: { method?: string; body?: unknown; headers?: Record<string, string> } = {},
): Promise<T> {
  const headers: Record<string, string> = { ...(options.headers ?? {}) }
  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
  }
  let response: Response
  try {
    response = await fetch(BASE + path, {
      method: options.method ?? 'GET',
      headers,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    })
  } catch {
    throw new ApiError(0, 'network', '无法连接服务，请确认 API 已在 8000 端口启动')
  }
  if (!response.ok) {
    let body: ErrorBody | null = null
    try {
      body = (await response.json()) as ErrorBody
    } catch {
      // 非 JSON 错误体：使用状态码兜底。
    }
    throw new ApiError(
      response.status,
      body?.error?.code ?? 'error',
      body?.error?.message ?? `请求失败（HTTP ${response.status}）`,
      body?.error?.fields,
      body?.request_id,
    )
  }
  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

export interface CustomerIn {
  client_id?: string
  display_name?: string
  contact_permission?: 'allowed' | 'denied'
  relationship?: string
  buyer?: Record<string, unknown>
  long_term_preferences?: Record<string, unknown>
}

export interface ConversationIn {
  customer_id?: string | null
  scenario?: string | null
  settings?: WritingSettings | null
  current_need?: string | null
  budget_cny?: number | null
  occasion?: string | null
  event_id?: string | null
  product_ids?: string[]
}

export interface ConversationPatch {
  expected_version: number
  customer_id?: string | null
  scenario?: string | null
  settings?: WritingSettings | null
  current_need?: string | null
  budget_cny?: number | null
  occasion?: string | null
  event_id?: string | null
  product_ids?: string[] | null
  status?: 'active' | 'closed' | null
}

export interface MessageIn {
  role: string
  content: string
  source?: string
  external_id?: string | null
}

export interface GenerationIn {
  expected_version: number
  idempotency_key?: string
  settings?: WritingSettings | null
}

export interface DraftPatch {
  text: string
  expected_revision: number
}

export interface DraftActionIn {
  action: 'selected' | 'copied' | 'discarded'
  copied_text?: string | null
  base_revision?: number | null
}

export interface PreferenceIn {
  kind: string
  original_text: string
  source: string
  explicit: boolean
}

export const api = {
  customers: {
    list: () => request<Customer[]>('/customers'),
    create: (body: CustomerIn) => request<Customer>('/customers', { method: 'POST', body }),
    get: (customerId: string) => request<Customer>(`/customers/${encodeURIComponent(customerId)}`),
  },
  conversations: {
    list: () => request<Conversation[]>('/conversations'),
    create: (body: ConversationIn = {}) => request<Conversation>('/conversations', { method: 'POST', body }),
    get: (conversationId: string) =>
      request<ConversationDetail>(`/conversations/${encodeURIComponent(conversationId)}`),
    patch: (conversationId: string, body: ConversationPatch) =>
      request<Conversation>(`/conversations/${encodeURIComponent(conversationId)}`, { method: 'PATCH', body }),
    postMessage: (conversationId: string, body: MessageIn) =>
      request<Message>(`/conversations/${encodeURIComponent(conversationId)}/messages`, { method: 'POST', body }),
    createGeneration: (conversationId: string, body: GenerationIn, idempotencyKey: string) =>
      request<Generation>(`/conversations/${encodeURIComponent(conversationId)}/generations`, {
        method: 'POST',
        body,
        headers: { 'Idempotency-Key': idempotencyKey },
      }),
  },
  analyze: (body: AnalyzeRequest) => request<AnalyzeResult>('/analyze', { method: 'POST', body }),
  catalog: {
    get: () => request<CatalogItem[]>('/catalog'),
  },
  generations: {
    get: (generationId: string) => request<Generation>(`/generations/${encodeURIComponent(generationId)}`),
  },
  drafts: {
    patch: (draftId: number, body: DraftPatch) =>
      request<Draft>(`/drafts/${draftId}`, { method: 'PATCH', body }),
    action: (draftId: number, body: DraftActionIn) =>
      request<DraftActionOut>(`/drafts/${draftId}/actions`, { method: 'POST', body }),
  },
  preferences: {
    list: (customerId: string) =>
      request<Preference[]>(`/customers/${encodeURIComponent(customerId)}/preferences`),
    create: (customerId: string, body: PreferenceIn) =>
      request<Preference>(`/customers/${encodeURIComponent(customerId)}/preferences`, { method: 'POST', body }),
    patch: (preferenceId: number, action: 'confirm' | 'revoke') =>
      request<Preference>(`/preferences/${preferenceId}`, { method: 'PATCH', body: { action } }),
  },
  settings: {
    model: () => request<ModelSettings>('/settings/model'),
    putModel: (body: ModelSettingsIn) =>
      request<ModelSettings>('/settings/model', { method: 'PUT', body }),
  },
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message
  }
  if (error instanceof Error) {
    return error.message
  }
  return '操作失败，请重试'
}
