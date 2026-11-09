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

export interface DatasourceSettings {
  supabase_url?: string
  supabase_service_key?: string
}

export interface DatasourceTestResult {
  ok: boolean
  message?: string
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
    throw new ApiError(0, 'network', '网络不可用，请稍后重试')
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
    // 导入示例客户：由服务端把合成示例客户写入运行库（不覆盖已有客户）。
    seed: () => request<Customer[]>('/customers/seed', { method: 'POST' }),
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
  datasource: {
    get: () => request<DatasourceSettings>('/settings/datasource'),
    put: (body: DatasourceSettings) =>
      request<DatasourceSettings>('/settings/datasource', { method: 'PUT', body }),
    test: (body: DatasourceSettings) =>
      request<DatasourceTestResult>('/settings/datasource/test', { method: 'POST', body }),
  },
}

// 面向用户的错误文案：不展示请求 ID 与错误码；网络/5xx/冲突等常见情形给固定友好话术，
// 其余按服务端 message 字段展示（不追加内部细节）。422 带 fields 时按字段名映射友好提示。
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    switch (error.status) {
      case 0:
        return '网络不可用，请稍后重试'
      case 404:
        return '内容不存在或已被移除，请刷新后重试'
      case 409:
        return '内容已被更新，请刷新后重试'
      case 422: {
        if (error.fields) {
          const keys = Object.keys(error.fields).join(' ')
          if (keys.includes('event')) {
            return '活动邀请需要选择具体活动'
          }
          if (keys.includes('scenario')) {
            return '请先选择沟通场景'
          }
          if (keys.includes('customer')) {
            return '所选客户不存在，请刷新后重试'
          }
          return '请补充必要信息后重试'
        }
        return error.message || '请求信息不完整，请检查后重试'
      }
      case 429:
        return '已有进行中的生成任务，请稍后再试'
      case 500:
        return '服务暂时不可用，请稍后重试'
      case 502:
        return '分析服务暂时不可用，请稍后重试'
      default:
        return error.message || '操作失败，请重试'
    }
  }
  if (error instanceof Error) {
    return error.message
  }
  return '操作失败，请重试'
}
