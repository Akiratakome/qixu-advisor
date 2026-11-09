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

// 活动邀请下拉：目前 /api/v1 未提供活动目录端点，先使用与 data/fictional/events.json 一致的
// 已冻结虚构活动；后端提供端点后改为接口读取。
export interface EventOption {
  event_id: string
  name: string
  start_at: string
}

export const EVENTS: EventOption[] = [
  { event_id: 'EVT-CITRUS', name: '青岚午后试香', start_at: '2026-11-14 14:00' },
  { event_id: 'EVT-WOOD', name: '木质气息小聚', start_at: '2026-11-21 16:00' },
]

// 发起对话行：缘由/需求输入的占位提示按场景切换；留空时由后端按默认值生成。
export const COLD_NEED_PLACEHOLDERS: Record<Scenario, string> = {
  生日与节庆: '祝福缘由，如：客户今天生日',
  产品推荐: '一句话说清为谁选香、喜欢与预算，可留空',
  购后关怀: '回访事由，如：询问使用感受',
  沉睡唤醒: '关系背景，如：曾购青岚、喜欢柑橘',
  活动邀请: '活动邀约事由，可留空',
  价格异议: '客户对价格或优惠的具体顾虑',
}
