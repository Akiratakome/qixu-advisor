import type { Message } from '../api'

function isAdvisor(role: string): boolean {
  return role === 'advisor' || role === 'assistant'
}

export default function MessageStream({ messages }: { messages: Message[] }) {
  if (messages.length === 0) {
    return (
      <div className="empty-hint">
        <p>还没有消息。</p>
        <p>在下方粘贴对话（每行一条，可用「客户：」「顾问：」前缀），或直接输入顾问话术。</p>
      </div>
    )
  }
  return (
    <div className="message-stream">
      {messages.map((message) => (
        <div key={message.message_id} className={`bubble-row ${isAdvisor(message.role) ? 'advisor' : 'client'}`}>
          <div className="bubble">
            <div className="bubble-meta">{isAdvisor(message.role) ? '顾问' : '客户'}</div>
            <div className="bubble-text">{message.content}</div>
          </div>
        </div>
      ))}
    </div>
  )
}
