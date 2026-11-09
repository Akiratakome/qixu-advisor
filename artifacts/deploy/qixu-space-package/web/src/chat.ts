// 对话记录解析与场景常量（与组件分离，供多处复用）。

export const SCENARIOS = ['生日与节庆', '产品推荐', '购后关怀', '沉睡唤醒', '活动邀请', '价格异议'] as const

export type Scenario = (typeof SCENARIOS)[number]

const CLIENT_PREFIXES = ['客户：', '客户:']
const ADVISOR_PREFIXES = ['顾问：', '顾问:']

export interface ParsedLine {
  role: string
  content: string
}

export function parseChatLines(value: string): ParsedLine[] {
  const lines: ParsedLine[] = []
  for (const raw of value.split('\n')) {
    const line = raw.trim()
    if (!line) {
      continue
    }
    let role = 'client'
    let content = line
    const advisorPrefix = ADVISOR_PREFIXES.find((prefix) => line.startsWith(prefix))
    if (advisorPrefix) {
      role = 'advisor'
      content = line.slice(advisorPrefix.length)
    } else {
      const clientPrefix = CLIENT_PREFIXES.find((prefix) => line.startsWith(prefix))
      if (clientPrefix) {
        content = line.slice(clientPrefix.length)
      }
    }
    lines.push({ role, content })
  }
  return lines
}

export function isScenario(value: string): value is Scenario {
  return (SCENARIOS as readonly string[]).includes(value)
}
