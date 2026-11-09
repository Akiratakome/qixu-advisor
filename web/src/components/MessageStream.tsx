import type { Message } from '../api'

function isAdvisor(role: string): boolean {
  return role === 'advisor' || role === 'assistant'
}

export default function MessageStream({ messages }: { messages: Message[] }) {
  if (messages.length === 0) {
    return (
      <div className="empty-hint">
        <p>还没有消息。</p>
        <p>添加聊天记录进行分析；记录顾问与顾客的对话，自动理解这轮需求。</p>
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
